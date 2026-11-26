package powershock;

import lejos.hardware.device.DeviceIdentifier;
import lejos.hardware.port.MotorPort;
import lejos.hardware.port.Port;
import lejos.hardware.port.SensorPort;

/**
 * Prints what is plugged into each EV3 port as one JSON line, e.g.
 *   {"A":"OUTPUT_TACHO:MINITACHO","B":"OUTPUT_TACHO:TACHO",...,"S1":"UART:COL-REFLECT"}
 * Started over SSH by the PC console (pc/ev3_brick.py); it never touches the LCD.
 */
public final class PortProbe {
    public static void main(String[] args) {
        Port[] ports = {MotorPort.A, MotorPort.B, MotorPort.C, MotorPort.D,
                SensorPort.S1, SensorPort.S2, SensorPort.S3, SensorPort.S4};
        String[] names = {"A", "B", "C", "D", "S1", "S2", "S3", "S4"};
        StringBuilder out = new StringBuilder("{");
        for (int i = 0; i < ports.length; i++) {
            String sig;
            DeviceIdentifier id = null;
            try {
                id = new DeviceIdentifier(ports[i]);
                sig = id.getDeviceSignature(true);
            } catch (Throwable t) {
                sig = "ERROR:" + t.getClass().getSimpleName();
            } finally {
                if (id != null) {
                    try {
                        id.close();
                    } catch (Throwable ignored) {
                    }
                }
            }
            if (i > 0) {
                out.append(',');
            }
            out.append('"').append(names[i]).append("\":\"").append(clean(sig)).append('"');
        }
        System.out.println(out.append('}'));
        System.exit(0);
    }

    private static String clean(String s) {
        if (s == null) {
            return "";
        }
        StringBuilder b = new StringBuilder();
        for (char c : s.toCharArray()) {
            b.append(c == '"' || c == '\\' || c < 0x20 ? ' ' : c);
        }
        return b.toString().trim();
    }
}
