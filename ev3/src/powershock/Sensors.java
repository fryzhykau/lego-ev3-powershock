package powershock;

import lejos.hardware.port.Port;
import lejos.hardware.port.SensorPort;
import lejos.hardware.port.UARTPort;
import lejos.hardware.sensor.EV3ColorSensor;
import lejos.hardware.sensor.EV3GyroSensor;
import lejos.hardware.sensor.EV3IRSensor;
import lejos.hardware.sensor.EV3UltrasonicSensor;
import lejos.hardware.sensor.SensorModes;
import lejos.robotics.SampleProvider;

/**
 * Reads the EV3 sensors the console uses for its live map, on its own thread, so a slow
 * sensor can never hold up driving. Sensors are opened once they are detected and read
 * about 20 times a second; the latest readings are appended to the status line:
 *   " s1=ir:37"   infrared, proximity 0..100 (100 = nothing in range)
 *   " s2=us:123"  ultrasonic, distance in cm (255 = nothing in range)
 *   " s3=col:5"   colour sensor, leJOS colour ID (-1 none, 0 red, 1 green, 2 blue, 3 yellow, 6 white, 7 black, 13 brown)
 *   " s4=gy:-45"  gyro, angle in degrees since it was opened
 * Touch and NXT sensors are left alone.
 */
final class Sensors implements Runnable {
    static final int CONN_UART = 122;
    static final int TYPE_COLOR = 29, TYPE_US = 30, TYPE_GYRO = 32, TYPE_IR = 33;
    private static final Port[] PORTS = {SensorPort.S1, SensorPort.S2, SensorPort.S3, SensorPort.S4};
    private static final long RETRY_MS = 3000;

    private final SensorModes[] open = new SensorModes[4];
    private final SampleProvider[] mode = new SampleProvider[4];
    private final String[] kind = new String[4];
    private final long[] retryAt = new long[4];
    private final float[] sample = new float[4];
    private volatile String line = "";
    private volatile boolean running = true;

    /** Latest readings, e.g. " s3=col:5 s4=ir:37" (empty if none). */
    String telemetry() {
        return line;
    }

    void stop() {
        running = false;
    }

    public void run() {
        while (running) {
            StringBuilder b = new StringBuilder();
            long now = System.currentTimeMillis();
            for (int i = 0; i < 4; i++) {
                try {
                    if (open[i] == null && now >= retryAt[i]) {
                        tryOpen(i, now);
                    }
                    if (mode[i] != null) {
                        mode[i].fetchSample(sample, 0);
                        b.append(" s").append(i + 1).append('=').append(kind[i]).append(':').append(value(i, sample[0]));
                    }
                } catch (Throwable e) {
                    close(i); // unplugged or misbehaving: try again later
                    retryAt[i] = now + RETRY_MS;
                }
            }
            line = b.toString();
            try {
                Thread.sleep(50);
            } catch (InterruptedException e) {
                break;
            }
        }
        for (int i = 0; i < 4; i++) {
            close(i);
        }
    }

    /**
     * What an EV3 sensor says it is, from the name of its first mode ("IR-PROX", "COL-REFLECT",
     * "US-DIST-CM", "GYRO-ANG"). Under leJOS the connection manager leaves the type of EV3
     * sensors unknown (125), so the sensor itself is asked. Takes up to a second or two.
     */
    private static int askType(Port p) {
        UARTPort u = p.open(UARTPort.class);
        try {
            if (!u.initialiseSensor(0)) {
                return 0;
            }
            String name = u.getModeName(0);
            if (name == null) {
                return 0;
            }
            if (name.startsWith("IR-")) {
                return TYPE_IR;
            }
            if (name.startsWith("COL-")) {
                return TYPE_COLOR;
            }
            if (name.startsWith("US-")) {
                return TYPE_US;
            }
            if (name.startsWith("GYRO-") || name.startsWith("GYR")) {
                return TYPE_GYRO;
            }
            return 0;
        } finally {
            u.close();
        }
    }

    private void tryOpen(int i, long now) {
        int[] c = PortWatch.sensorCodes(i);
        if (c[0] != CONN_UART) {
            return;
        }
        int type = c[1];
        if (type != TYPE_IR && type != TYPE_COLOR && type != TYPE_US && type != TYPE_GYRO) {
            type = askType(PORTS[i]);
            if (type == 0) {
                retryAt[i] = now + RETRY_MS; // not one the map uses, or still starting up
                return;
            }
        }
        switch (type) {
            case TYPE_IR: {
                EV3IRSensor s = new EV3IRSensor(PORTS[i]);
                open[i] = s;
                mode[i] = s.getDistanceMode();
                kind[i] = "ir";
                break;
            }
            case TYPE_COLOR: {
                EV3ColorSensor s = new EV3ColorSensor(PORTS[i]);
                open[i] = s;
                mode[i] = s.getColorIDMode();
                kind[i] = "col";
                break;
            }
            case TYPE_US: {
                EV3UltrasonicSensor s = new EV3UltrasonicSensor(PORTS[i]);
                open[i] = s;
                mode[i] = s.getDistanceMode();
                kind[i] = "us";
                break;
            }
            case TYPE_GYRO: {
                EV3GyroSensor s = new EV3GyroSensor(PORTS[i]);
                open[i] = s;
                mode[i] = s.getAngleMode();
                kind[i] = "gy";
                break;
            }
            default:
                break;
        }
    }

    private String value(int i, float v) {
        if ("us".equals(kind[i])) {
            // metres, Infinity when nothing is in range
            return Float.isInfinite(v) || Float.isNaN(v) || v > 2.55f ? "255" : Integer.toString(Math.round(v * 100));
        }
        if (Float.isNaN(v) || Float.isInfinite(v)) {
            return "ir".equals(kind[i]) ? "100" : "0";
        }
        return Integer.toString(Math.round(v));
    }

    private void close(int i) {
        SensorModes s = open[i];
        open[i] = null;
        mode[i] = null;
        kind[i] = null;
        if (s instanceof java.io.Closeable) {
            try {
                ((java.io.Closeable) s).close();
            } catch (Throwable ignored) {
            }
        }
    }
}
