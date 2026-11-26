package powershock;

import lejos.hardware.Button;
import lejos.hardware.lcd.LCD;

/**
 * Direct Bluetooth variant: DS4 -> EV3 with no PC. Run with the controller's MAC
 * as the first argument, or set DS4_MAC below. Turn Bluetooth on in the leJOS
 * menu, start this program, then hold Share + PS on the controller.
 *
 * Same controls as the WiFi variant. Motors stop if no report arrives for 500 ms,
 * then the program reconnects. ESCAPE on the brick exits.
 */
public final class DS4Drive {
    static final String DS4_MAC = "00:00:00:00:00:00"; // put your controller's address here
    static final long WATCHDOG_MS = 500;

    private static volatile DS4State state;
    private static volatile long lastReportAt;
    private static volatile String status = "starting";

    public static void main(String[] args) throws Exception {
        String mac = args.length > 0 ? args[0] : DS4_MAC;
        final DS4 ds4 = new DS4(mac);
        Drive drive = new Drive();

        LCD.clear();
        LCD.drawString("PowerShock BT " + Version.get(), 0, 0);
        LCD.drawString(mac, 0, 1);
        LCD.drawString("ESC = exit", 0, 7);

        Thread reader = new Thread(new Runnable() {
            public void run() {
                readLoop(ds4);
            }
        }, "ds4");
        reader.setDaemon(true);
        reader.start();

        PortWatch.prime();
        long lastRefresh = 0;
        try {
            while (!Button.ESCAPE.isDown()) {
                if (System.currentTimeMillis() - lastRefresh >= 250) {
                    lastRefresh = System.currentTimeMillis();
                    drive.refresh();
                }
                DS4State s = state;
                boolean fresh = s != null && System.currentTimeMillis() - lastReportAt < WATCHDOG_MS;
                if (fresh) {
                    int[] m = Mixer.mix(s.lx, s.ly, s.ry, s.r2, s.cross);
                    drive.set(m[0], m[1], m[2]);
                    LCD.drawString(pad(m[0] + " " + m[1] + " " + m[2]), 0, 5);
                } else {
                    drive.stop();
                }
                LCD.drawString(pad(status), 0, 3);
                Thread.sleep(20);
            }
        } finally {
            drive.close();
            ds4.close();
        }
    }

    private static void readLoop(DS4 ds4) {
        while (true) {
            try {
                status = "Share+PS to pair";
                ds4.connect();
                status = "Connected!";
                long lastSeen = System.currentTimeMillis();
                while (System.currentTimeMillis() - lastSeen < WATCHDOG_MS) {
                    DS4State s = ds4.read();
                    if (s != null) {
                        state = s;
                        lastSeen = System.currentTimeMillis();
                        lastReportAt = lastSeen;
                    }
                }
                status = "timeout, retry";
            } catch (DS4.DS4Exception e) {
                status = e.getMessage();
                sleep(1000);
            } finally {
                ds4.close();
            }
        }
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ignored) {
        }
    }

    private static String pad(String s) {
        if (s.length() > 18) {
            return s.substring(0, 18);
        }
        StringBuilder b = new StringBuilder(s);
        while (b.length() < 18) {
            b.append(' ');
        }
        return b.toString();
    }
}
