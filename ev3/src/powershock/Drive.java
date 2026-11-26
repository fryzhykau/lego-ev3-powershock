package powershock;

import lejos.hardware.motor.BaseRegulatedMotor;
import lejos.hardware.motor.EV3LargeRegulatedMotor;
import lejos.hardware.motor.EV3MediumRegulatedMotor;
import lejos.hardware.port.MotorPort;
import lejos.hardware.port.Port;

/**
 * Motor outputs, claimed only when a motor is actually plugged in.
 *
 * Driving roles: B = left, C = right, aux (right stick) = A, or D if A is empty.
 * Every detected motor is claimed, so each one can also be tested on its own from
 * the PC (see test()). A port stays free until a motor shows up there, so the brick
 * keeps detecting it and a motor plugged in later appears within a quarter of a second.
 */
public final class Drive {
    private static final Port[] PORTS = {MotorPort.A, MotorPort.B, MotorPort.C, MotorPort.D};
    private static final char[] NAMES = {'A', 'B', 'C', 'D'};
    private static final int A = 0, B = 1, C = 2, D = 3;
    /** A held "run" test stops if the PC doesn't repeat it within this time. */
    private static final long TEST_HOLD_MS = 400;
    /** Limits for commands from the network, whoever sends them. */
    static final int MAX_TEST_DEG = 3600, MAX_ANGLE = 720;

    private final BaseRegulatedMotor[] motors = new BaseRegulatedMotor[4];
    private final int[] lastDir = new int[4];
    /** While a test owns a motor, driving leaves it alone. */
    private final long[] testUntil = new long[4];
    private final boolean[] testRotating = new boolean[4];

    /** Opens motors on ports where one has been plugged in. Call a few times a second. */
    public void refresh() {
        for (int i = 0; i < 4; i++) {
            claimIfPresent(i);
        }
        long now = System.currentTimeMillis();
        for (int i = 0; i < 4; i++) {
            BaseRegulatedMotor m = motors[i];
            if (m == null) {
                continue;
            }
            if (testRotating[i] && !m.isMoving()) {
                testRotating[i] = false; // an exact move finished by itself
            } else if (testRotating[i] && now > testUntil[i]) {
                testRotating[i] = false; // took far longer than it should (blocked?): give up
                testUntil[i] = 0;
                m.stop(true);
            }
            if (!testRotating[i] && testUntil[i] != 0 && now > testUntil[i]) {
                testUntil[i] = 0;
                m.stop(true); // a held test was released
                lastDir[i] = 0;
            }
        }
    }

    private void claimIfPresent(int i) {
        if (motors[i] != null) {
            return;
        }
        int[] codes = PortWatch.motorCodes(i);
        if (codes[0] != PortWatch.CONN_TACHO) {
            return;
        }
        try {
            motors[i] = codes[1] == PortWatch.TYPE_MEDIUM
                    ? new EV3MediumRegulatedMotor(PORTS[i])
                    : new EV3LargeRegulatedMotor(PORTS[i]);
        } catch (RuntimeException e) {
            motors[i] = null; // try again on the next refresh
        }
    }

    private int auxPort() {
        return motors[A] != null ? A : motors[D] != null ? D : -1;
    }

    private boolean testing(int i) {
        return testRotating[i] || testUntil[i] > System.currentTimeMillis();
    }

    /** Each value is a percentage in [-100, 100]. */
    public void set(int l, int r, int a) {
        apply(B, l);
        apply(C, r);
        int aux = auxPort();
        if (aux >= 0) {
            apply(aux, a);
        }
    }

    public void stop() {
        for (int i = 0; i < 4; i++) {
            apply(i, 0);
        }
    }

    /**
     * Test one motor from the PC:
     *   run <pct>       run at pct (-100..100) for as long as the PC keeps repeating it
     *   rotate <deg> <pct>  turn exactly deg degrees at pct speed
     *   stop            stop it now
     */
    public void test(char port, String action, int a, int b) {
        int i = port - 'A';
        if (i < 0 || i > 3 || motors[i] == null) {
            return;
        }
        BaseRegulatedMotor m = motors[i];
        if (action.equals("zero")) {
            zero(i);
        } else if (action.equals("stop")) {
            testRotating[i] = false;
            testUntil[i] = 0;
            m.stop(true);
            lastDir[i] = 0;
        } else if (action.equals("run")) {
            testRotating[i] = false;
            testUntil[i] = System.currentTimeMillis() + TEST_HOLD_MS;
            int dir = Integer.signum(a);
            m.setSpeed(Math.min(100, Math.abs(a)) * m.getMaxSpeed() / 100f);
            if (dir == 0) {
                m.stop(true);
            } else if (dir != lastDir[i]) {
                if (dir > 0) {
                    m.forward();
                } else {
                    m.backward();
                }
            }
            lastDir[i] = dir;
        } else if (action.equals("rotate")) {
            int deg = Math.max(-MAX_TEST_DEG, Math.min(MAX_TEST_DEG, a));
            float speed = Math.max(5, Math.min(100, Math.abs(b))) * m.getMaxSpeed() / 100f;
            m.setSpeed(speed);
            testRotating[i] = true;
            // time it should take, twice over plus 2 s; refresh() stops it after that
            testUntil[i] = System.currentTimeMillis() + 2000 + (long) (2000f * Math.abs(deg) / Math.max(1f, speed));
            lastDir[i] = 0;
            m.rotate(deg, true);
        }
    }

    /** Last angle sent to each position-controlled port, so we only re-aim when it changes. */
    private final int[] posTarget = new int[4];
    private final boolean[] posActive = new boolean[4];

    /**
     * One port under the PC's controls mapping:
     *   's', pct          run at pct (-100..100)
     *   'p', deg, speed   turn to deg (relative to the centre set with zero) at speed %
     *   '-'               not controlled by the mapping: stopped if it was moving, then left alone
     */
    public void command(int i, char mode, int a, int b) {
        BaseRegulatedMotor m = motors[i];
        if (m == null || testing(i)) {
            return;
        }
        if (mode == '-') {
            if (lastDir[i] != 0 || posActive[i]) {
                m.stop(true);
            }
            lastDir[i] = 0;
            posActive[i] = false;
            return;
        }
        if (mode == 's') {
            posActive[i] = false;
            apply(i, Math.max(-100, Math.min(100, a)));
        } else if (mode == 'p') {
            a = Math.max(-MAX_ANGLE, Math.min(MAX_ANGLE, a));
            int speed = Math.max(5, Math.min(100, b));
            if (!posActive[i] || Math.abs(a - posTarget[i]) >= 1) {
                m.setSpeed(speed * m.getMaxSpeed() / 100f);
                m.rotateTo(a, true);
                posTarget[i] = a;
                posActive[i] = true;
                lastDir[i] = 0;
            }
        }
    }

    /** Input stopped arriving: speed ports stop; angle ports hold where they are. */
    public void holdAll() {
        for (int i = 0; i < 4; i++) {
            if (motors[i] == null || testing(i)) {
                continue;
            }
            if (posActive[i]) {
                continue; // rotateTo already holds the angle
            }
            apply(i, 0);
        }
    }

    /** Makes the motor's current position its centre (0°), e.g. wheels straight. */
    public void zero(int i) {
        if (motors[i] != null) {
            motors[i].resetTachoCount();
            posTarget[i] = 0;
            posActive[i] = false;
        }
    }

    /** Stops every motor, including any test. */
    public void stopAll() {
        for (int i = 0; i < 4; i++) {
            posActive[i] = false;
            testRotating[i] = false;
            testUntil[i] = 0;
            if (motors[i] != null) {
                motors[i].stop(true);
            }
            lastDir[i] = 0;
        }
    }

    public void close() {
        stopAll();
        for (int i = 0; i < 4; i++) {
            if (motors[i] != null) {
                motors[i].close();
                motors[i] = null;
            }
        }
    }

    /**
     * Live readings for the PC, for each claimed motor:
     * " mB=<tacho deg>:<speed deg/s>:<stalled 0/1>:<role>" where role is L, R, X (aux) or -.
     */
    public String telemetry() {
        StringBuilder b = new StringBuilder();
        int aux = auxPort();
        for (int i = 0; i < 4; i++) {
            BaseRegulatedMotor m = motors[i];
            if (m == null) {
                continue;
            }
            char role = i == B ? 'L' : i == C ? 'R' : i == aux ? 'X' : '-';
            b.append(" m").append(NAMES[i]).append('=').append(m.getTachoCount()).append(':')
                    .append(Math.round(m.getRotationSpeed())).append(':').append(m.isStalled() ? 1 : 0)
                    .append(':').append(role);
        }
        return b.toString();
    }

    private void apply(int i, int pct) {
        BaseRegulatedMotor m = motors[i];
        if (m == null || testing(i)) {
            return;
        }
        int dir = Integer.signum(pct);
        if (dir == 0) {
            if (lastDir[i] != 0) {
                m.stop(true);
            }
        } else {
            m.setSpeed(Math.abs(pct) * m.getMaxSpeed() / 100f);
            if (dir != lastDir[i]) {
                if (dir > 0) {
                    m.forward();
                } else {
                    m.backward();
                }
            }
        }
        lastDir[i] = dir;
    }
}
