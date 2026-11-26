import java.rmi.Naming;

import lejos.remote.ev3.RMIMenu;

/**
 * Talks to the leJOS menu on the brick over RMI (port 1099), the same way the
 * leJOS Eclipse plugin does. Runs on the PC; compiled by ev3_console.py.
 *
 *   java -cp tools;lib/ev3classes.jar BrickMenu <host> info|run <prog>|stop
 *
 * Prints one JSON object. Exit code 0 on success.
 */
public final class BrickMenu {
    public static void main(String[] args) {
        if (args.length < 2) {
            fail("usage: BrickMenu <host> info|run <program>|stop");
        }
        System.setProperty("sun.rmi.transport.tcp.responseTimeout", "8000");
        System.setProperty("sun.rmi.transport.connectionTimeout", "5000");
        try {
            RMIMenu menu = (RMIMenu) Naming.lookup("//" + args[0] + "/RemoteMenu");
            String cmd = args[1];
            if (cmd.equals("info")) {
                StringBuilder progs = new StringBuilder();
                for (String p : menu.getProgramNames()) {
                    if (progs.length() > 0) {
                        progs.append(',');
                    }
                    progs.append(q(p));
                }
                String battery = "null";
                try {
                    lejos.remote.ev3.RMIEV3 ev3 = (lejos.remote.ev3.RMIEV3) Naming.lookup("//" + args[0] + "/RemoteEV3");
                    lejos.remote.ev3.RMIBattery b = ev3.getBattery();
                    battery = "{\"volts\":" + b.getVoltage() + ",\"batteryAmps\":" + b.getBatteryCurrent()
                            + ",\"motorAmps\":" + b.getMotorCurrent() + "}";
                } catch (Exception e) {
                    battery = "{\"error\":" + q(e.getClass().getSimpleName() + ": " + e.getMessage()) + "}";
                }
                System.out.println("{\"ok\":true,\"battery\":" + battery + ",\"name\":" + q(menu.getName())
                        + ",\"version\":" + q(menu.getVersion())
                        + ",\"menuVersion\":" + q(menu.getMenuVersion())
                        + ",\"running\":" + q(menu.getExecutingProgramName())
                        + ",\"programs\":[" + progs + "]}");
            } else if (cmd.equals("run") && args.length > 2) {
                menu.runProgram(args[2]);
                System.out.println("{\"ok\":true}");
            } else if (cmd.equals("stop")) {
                menu.stopProgram();
                System.out.println("{\"ok\":true}");
            } else {
                fail("unknown command " + cmd);
            }
        } catch (Exception e) {
            fail(e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }

    private static void fail(String msg) {
        System.out.println("{\"ok\":false,\"error\":" + q(msg) + "}");
        System.exit(1);
    }

    private static String q(String s) {
        if (s == null) {
            return "null";
        }
        StringBuilder b = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            if (c == '"' || c == '\\') {
                b.append('\\').append(c);
            } else if (c < 0x20) {
                b.append(String.format("\\u%04x", (int) c));
            } else {
                b.append(c);
            }
        }
        return b.append('"').toString();
    }
}
