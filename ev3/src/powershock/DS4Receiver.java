package powershock;

import java.io.BufferedInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.util.Enumeration;

import lejos.hardware.Button;
import lejos.hardware.lcd.LCD;

/**
 * WiFi/network variant, EV3 side. Listens on TCP port 5000 for lines from the PC console
 * (pc/ev3_console.py), about 50 per second: "P ..." per-port commands, "M ..." motor tests,
 * or the older "left right aux" (each -100..100). The motors stop if nothing arrives for
 * 500 ms, and as soon as the connection drops. ESCAPE on the brick exits.
 *
 * Sends back "V <version>" once per connection, then "T ..." status lines: battery, ports,
 * motor angles, and sensor readings for the console's map (see Sensors).
 *
 * Only the main loop drives motors. Network reading and status sending run on their own
 * threads, so a slow or stuck connection can never hold up the watchdog or ESCAPE.
 */
public final class DS4Receiver {
    static final int PORT = 5000;
    static final long WATCHDOG_MS = 500;

    private static volatile int cmdL, cmdR, cmdA;
    private static volatile long lastCmdAt;
    /** When a motor was last told to turn: WiFi only looks for a better network while the robot stands still. */
    static volatile long movingAt;
    private static volatile boolean clientConnected;
    private static volatile boolean running = true;
    /** Status goes back to the PC on the same connection: "T <battery> <ports>" every 250 ms. */
    private static volatile java.io.OutputStream clientOut;
    static final long TELEMETRY_MS = 250;
    /** Longest line accepted; longer ones are dropped. */
    static final int MAX_LINE = 256;
    /** A connection that sends nothing valid for this long is closed, so others can connect. */
    static final int IDLE_MS = 5000;
    /** Most motor tests waiting at once; more are dropped. */
    static final int MAX_TESTS = 32;
    private static volatile String telemetry = "";

    public static void main(String[] args) throws Exception {
        PortWatch.prime(); // read every port while it's still free, before the motors claim them
        final Drive drive = new Drive();
        // When stopped from the PC (SIGTERM), release the motor ports so the brick's port
        // detection works again for the next program.
        Runtime.getRuntime().addShutdownHook(new Thread(new Runnable() {
            public void run() {
                try {
                    drive.close();
                } catch (Throwable ignored) {
                }
            }
        }));
        final ServerSocket server = new ServerSocket(PORT);

        Thread net = new Thread(new Runnable() {
            public void run() {
                serve(server);
            }
        }, "net");
        net.setDaemon(true);
        net.start();
        Thread status = new Thread(new Runnable() {
            public void run() {
                sendStatus();
            }
        }, "status");
        status.setDaemon(true);
        status.start();
        final Sensors sensors = new Sensors(); // IR, colour, ultrasonic and gyro readings for the console's map
        Thread sense = new Thread(sensors, "sensors");
        sense.setDaemon(true);
        sense.start();
        final WifiRoam wifi = new WifiRoam(); // moves to the strongest saved WiFi network
        Thread roam = new Thread(wifi, "wifi");
        roam.setDaemon(true);
        roam.start();

        LCD.clear();
        LCD.drawString(pad("PowerShock " + Version.get()), 0, 0);
        LCD.drawString("port " + PORT, 0, 1);
        drawAddresses();
        LCD.drawString("ESC = exit", 0, 7);

        long lastTelemetry = 0;
        long lastRefresh = 0;
        try {
            while (running && !Button.ESCAPE.isDown()) {
                long now = System.currentTimeMillis();
                if (now - lastRefresh >= 250) {
                    lastRefresh = now;
                    drive.refresh(); // claim motors as they get plugged in
                }
                if (clientOut != null && now - lastTelemetry >= TELEMETRY_MS) {
                    lastTelemetry = now;
                    telemetry = "T " + PortWatch.snapshot() + drive.telemetry() + sensors.telemetry() + wifi.telemetry() + "\n"; // sent by the "status" thread
                }
                String[] t;
                while ((t = tests.poll()) != null) {
                    try {
                        int a = t.length > 3 ? Integer.parseInt(t[3]) : 0;
                        int b = t.length > 4 ? Integer.parseInt(t[4]) : 50;
                        if (t[1].equals("*")) {
                            drive.stopAll();
                        } else {
                            drive.test(t[1].charAt(0), t[2], a, b);
                        }
                    } catch (RuntimeException ignored) {
                        // malformed test command
                    }
                }
                String[] pl = portLine;
                boolean mapped = pl != null && System.currentTimeMillis() - portLineAt < WATCHDOG_MS;
                boolean fresh = mapped || System.currentTimeMillis() - lastCmdAt < WATCHDOG_MS;
                if (mapped) {
                    applyPortLine(drive, pl);
                } else if (fresh) {
                    drive.set(cmdL, cmdR, cmdA);
                } else {
                    drive.holdAll(); // speed ports stop, steering holds its angle
                }
                LCD.drawString(pad(clientConnected ? (fresh ? "driving" : "no data") : "waiting"), 0, 5);
                LCD.drawString(pad(cmdL + " " + cmdR + " " + cmdA), 0, 6);
                Thread.sleep(20);
            }
        } finally {
            running = false;
            sensors.stop();
            wifi.stop();
            drive.close();
            server.close();
        }
    }

    /** Sends the latest status line to the PC 4 times a second. Blocking here can't stop the motors' watchdog. */
    private static void sendStatus() {
        String last = null;
        java.io.OutputStream greeted = null;
        while (running) {
            java.io.OutputStream out = clientOut;
            String t = telemetry;
            if (out != null && out != greeted) {
                greeted = out; // a new connection: say which version this is, first
                try {
                    out.write(("V " + Version.get() + "\n").getBytes("US-ASCII"));
                    out.flush();
                } catch (IOException e) {
                    // the reader thread notices the drop
                }
            }
            if (out != null && t != last && t.length() > 0) {
                last = t;
                try {
                    out.write(t.getBytes("US-ASCII"));
                    out.flush();
                } catch (IOException e) {
                    // the reader thread notices the drop and cleans up
                }
            }
            try {
                Thread.sleep(50);
            } catch (InterruptedException e) {
                return;
            }
        }
    }

    private static void serve(ServerSocket server) {
        while (running) {
            Socket s = null;
            try {
                s = server.accept();
                s.setTcpNoDelay(true);
                s.setSoTimeout(1000);
                clientConnected = true;
                clientOut = s.getOutputStream();
                InputStream in = new BufferedInputStream(s.getInputStream());
                StringBuilder line = new StringBuilder();
                boolean tooLong = false;
                long lastValid = System.currentTimeMillis();
                while (running) {
                    int c;
                    try {
                        c = in.read();
                    } catch (SocketTimeoutException e) {
                        c = -2; // nothing for a second; the main loop's watchdog stops the motors
                    }
                    if (c == -1) {
                        break; // closed by the PC
                    }
                    if (c == '\n') {
                        if (!tooLong && line.length() > 0) {
                            try {
                                if (parse(line.toString())) {
                                    lastValid = System.currentTimeMillis();
                                }
                            } catch (RuntimeException ignored) {
                                // anything odd in one line must not end the connection
                            }
                        }
                        line.setLength(0);
                        tooLong = false;
                    } else if (c >= 0 && c != '\r') {
                        if (line.length() < MAX_LINE) {
                            line.append((char) c);
                        } else {
                            tooLong = true; // drop the rest of this line
                        }
                    }
                    if (System.currentTimeMillis() - lastValid > IDLE_MS) {
                        break; // silent or talking nonsense: let someone else connect
                    }
                }
            } catch (Throwable e) {
                // client dropped, server closed, or something unexpected: accept again
            } finally {
                clientConnected = false;
                clientOut = null;
                portLine = null;
                lastCmdAt = 0;
                queueTest(new String[] {"M", "*", "stop"}); // connection gone: stop everything now
                if (s != null) {
                    try {
                        s.close();
                    } catch (IOException ignored) {
                    }
                }
            }
        }
    }

    /** Latest "P A=s:40 B=p:30:60 C=- D=-" line from the PC's controls mapping. */
    private static volatile String[] portLine;
    private static volatile long portLineAt;

    private static void applyPortLine(Drive drive, String[] p) {
        for (int k = 1; k < p.length; k++) {
            String item = p[k];
            if (item.length() < 3 || item.charAt(1) != '=') {
                continue;
            }
            int port = item.charAt(0) - 'A';
            if (port < 0 || port > 3) {
                continue;
            }
            String[] v = item.substring(2).split(":");
            try {
                if (v[0].equals("s") && v.length >= 2) {
                    int speed = Integer.parseInt(v[1]);
                    if (speed != 0) {
                        movingAt = System.currentTimeMillis();
                    }
                    drive.command(port, 's', speed, 0);
                } else if (v[0].equals("p") && v.length >= 3) {
                    drive.command(port, 'p', Integer.parseInt(v[1]), Integer.parseInt(v[2]));
                } else if (v[0].equals("-")) {
                    drive.command(port, '-', 0, 0); // switched to "not used": stop it if it was moving
                }
            } catch (NumberFormatException ignored) {
                // malformed item
            }
        }
    }

    /** Motor tests from the PC, carried out by the main loop (the only thread that drives motors). */
    private static final java.util.concurrent.ConcurrentLinkedQueue<String[]> tests =
            new java.util.concurrent.ConcurrentLinkedQueue<String[]>();

    /**
     * Accepts "l r a" (driving) or "M <port|*> <run|rotate|stop> [value] [speed]" (testing one
     * motor); ignores anything malformed.
     */
    static boolean parse(String line) {
        String[] p = line.trim().split("\\s+");
        if (p.length >= 3 && p[0].equals("M")) {
            queueTest(p);
            return true;
        }
        if (p.length >= 2 && p[0].equals("P")) {
            portLine = p;
            portLineAt = System.currentTimeMillis();
            return true;
        }
        if (p.length != 3) {
            return false;
        }
        try {
            int l = clamp(Integer.parseInt(p[0]));
            int r = clamp(Integer.parseInt(p[1]));
            int a = clamp(Integer.parseInt(p[2]));
            cmdL = l;
            cmdR = r;
            cmdA = a;
            lastCmdAt = System.currentTimeMillis();
            if (l != 0 || r != 0 || a != 0) {
                movingAt = lastCmdAt;
            }
            return true;
        } catch (NumberFormatException ignored) {
            return false;
        }
    }

    private static void queueTest(String[] t) {
        if (t[1].equals("*")) {
            tests.clear(); // a stop-all goes ahead of anything still waiting
        } else if (tests.size() >= MAX_TESTS) {
            return;
        }
        tests.add(t);
    }

    private static int clamp(int v) {
        return Math.max(-100, Math.min(100, v));
    }

    private static void drawAddresses() {
        int row = 2;
        try {
            Enumeration<NetworkInterface> ifs = NetworkInterface.getNetworkInterfaces();
            while (ifs.hasMoreElements() && row <= 4) {
                NetworkInterface ni = ifs.nextElement();
                if (ni.isLoopback()) {
                    continue;
                }
                Enumeration<InetAddress> addrs = ni.getInetAddresses();
                while (addrs.hasMoreElements() && row <= 4) {
                    InetAddress a = addrs.nextElement();
                    if (a instanceof Inet4Address) {
                        LCD.drawString(pad(a.getHostAddress()), 0, row++);
                    }
                }
            }
        } catch (IOException e) {
            LCD.drawString("no IP?", 0, row);
        }
    }

    private static String pad(String s) {
        StringBuilder b = new StringBuilder(s);
        while (b.length() < 18) {
            b.append(' ');
        }
        return b.toString();
    }
}
