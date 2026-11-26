package powershock;

import lejos.hardware.Battery;
import lejos.internal.ev3.EV3AnalogPort;

/**
 * Live port and battery readings, cheap enough to poll several times a second.
 *
 * leJOS keeps the EV3's port detection (the kernel's "DCM" connection manager) in
 * shared memory, read by protected static methods on EV3AnalogPort. Subclassing it
 * lets us read those directly: no port is opened, so this works even on ports a
 * motor object already holds. Each port reports two numbers:
 *   connection: 125 tacho motor, 122 EV3 UART sensor, 121 EV3 analog (touch),
 *               119/118/120 NXT sensors, 126 nothing, ...
 *   device type: 7 large motor, 8 medium motor, 16 EV3 touch, 29 color,
 *               30 ultrasonic, 32 gyro, 33 infrared, 126 none, ...
 */
public final class PortWatch extends EV3AnalogPort {
    static final int CONN_TACHO = 125;
    static final int TYPE_LARGE = 7;
    static final int TYPE_MEDIUM = 8;

    /** {connection, device type} for motor port 0..3 (A..D): live if free, else as last seen. */
    static int[] motorCodes(int i) {
        int conn = getMotorPortType(i);
        int typ = getMotorType(i);
        if (conn == 0 && typ == 0 && lastFree[i] != null) {
            return lastFree[i];
        }
        return new int[] {conn, typ};
    }

    /** Last reading taken while a port was still free; see snapshot(). */
    private static final int[][] lastFree = new int[8][];

    private PortWatch() {
    }

    /** Diagnostic: prints a few readings with no ports opened. jrun -cp powershock-wifi.jar powershock.PortWatch */
    public static void main(String[] args) throws InterruptedException {
        prime();
        for (int i = 0; i < 6; i++) {
            System.out.println(snapshot());
            Thread.sleep(700);
        }
    }

    /**
     * Call once before opening any motors. Opening a port as a ConfigurationPort switches
     * the connection manager back on for it (a program that was killed leaves its motor
     * ports with detection off), so after a short settle we get a real reading for every
     * port, which is then remembered for the ports the motors are about to claim.
     */
    public static void prime() {
        lejos.hardware.port.Port[] ports = {
            lejos.hardware.port.MotorPort.A, lejos.hardware.port.MotorPort.B,
            lejos.hardware.port.MotorPort.C, lejos.hardware.port.MotorPort.D,
            lejos.hardware.port.SensorPort.S1, lejos.hardware.port.SensorPort.S2,
            lejos.hardware.port.SensorPort.S3, lejos.hardware.port.SensorPort.S4};
        lejos.hardware.port.ConfigurationPort[] open = new lejos.hardware.port.ConfigurationPort[ports.length];
        for (int i = 0; i < ports.length; i++) {
            try {
                open[i] = ports[i].open(lejos.hardware.port.ConfigurationPort.class);
            } catch (RuntimeException e) {
                open[i] = null; // already in use; we'll just read whatever it reports
            }
        }
        try {
            Thread.sleep(700); // the connection manager needs a moment to identify devices
        } catch (InterruptedException ignored) {
        }
        snapshot();
        for (lejos.hardware.port.ConfigurationPort c : open) {
            if (c != null) {
                c.close();
            }
        }
    }

    /**
     * leJOS turns the connection manager off for ports a program opens; they then read 0.
     * For those we report the last reading from before the port was opened, with "h"
     * (held) appended, e.g. "B=125:7h".
     */
    private static String codes(int idx, int conn, int typ) {
        if (conn == 0 && typ == 0) {
            int[] last = lastFree[idx];
            return last == null ? "0:0h" : last[0] + ":" + last[1] + "h";
        }
        lastFree[idx] = new int[] {conn, typ};
        return conn + ":" + typ;
    }

    /** "8.61 0.162 0.000 A=126:126 B=125:7 ... 4=126:126" */
    public static String snapshot() {
        StringBuilder b = new StringBuilder();
        b.append(fmt(Battery.getVoltage(), 2)).append(' ')
                .append(fmt(Battery.getBatteryCurrent(), 3)).append(' ')
                .append(fmt(Battery.getMotorCurrent(), 3));
        char[] motors = {'A', 'B', 'C', 'D'};
        for (int i = 0; i < 4; i++) {
            b.append(' ').append(motors[i]).append('=').append(codes(i, getMotorPortType(i), getMotorType(i)));
        }
        for (int i = 0; i < 4; i++) {
            b.append(' ').append(i + 1).append('=').append(codes(4 + i, getPortType(i), getAnalogSensorType(i)));
        }
        return b.toString();
    }

    private static String fmt(float v, int decimals) {
        // String.format is slow on the EV3's JVM; this is called 4 times a second.
        long scale = decimals == 2 ? 100 : 1000;
        long n = Math.round(v * scale);
        String s = Long.toString(Math.abs(n) / scale) + "." + pad(Math.abs(n) % scale, decimals);
        return n < 0 ? "-" + s : s;
    }

    private static String pad(long v, int width) {
        String s = Long.toString(v);
        while (s.length() < width) {
            s = "0" + s;
        }
        return s;
    }
}
