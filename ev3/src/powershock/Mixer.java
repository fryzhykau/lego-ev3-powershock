package powershock;

/**
 * Turns controller inputs into motor commands. Pure logic, no leJOS imports,
 * so it can be unit-tested on the PC. Keep it in sync with pc/ds4_mix.py.
 *
 * Inputs: sticks in [-1, 1] (up is negative Y, like the raw DS4 axes),
 * trigger in [0, 1]. Output: {left, right, aux} in [-100, 100].
 */
public final class Mixer {
    public static final double DEADZONE = 0.08;
    /** Speed without turbo; R2 fully pressed gives 100%. */
    public static final double BASE_SCALE = 0.5;

    private Mixer() {}

    public static int[] mix(double lx, double ly, double ry, double r2, boolean stop) {
        if (stop) {
            return new int[] {0, 0, 0};
        }
        double throttle = -deadzone(ly);
        double turn = deadzone(lx);
        double aux = -deadzone(ry);

        double left = throttle + turn;
        double right = throttle - turn;
        double max = Math.max(Math.abs(left), Math.abs(right));
        if (max > 1.0) {
            left /= max;
            right /= max;
        }

        double scale = BASE_SCALE + (1.0 - BASE_SCALE) * clamp(r2, 0.0, 1.0);
        return new int[] {pct(left * scale), pct(right * scale), pct(aux * scale)};
    }

    /** Removes the dead zone and rescales the rest back to the full [-1, 1] range. */
    static double deadzone(double v) {
        v = clamp(v, -1.0, 1.0);
        double a = Math.abs(v);
        if (a < DEADZONE) {
            return 0.0;
        }
        return Math.signum(v) * (a - DEADZONE) / (1.0 - DEADZONE);
    }

    static double clamp(double v, double lo, double hi) {
        return v < lo ? lo : (v > hi ? hi : v);
    }

    static int pct(double v) {
        return (int) Math.round(clamp(v, -1.0, 1.0) * 100.0);
    }
}
