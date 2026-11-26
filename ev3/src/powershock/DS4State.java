package powershock;

/**
 * One parsed DualShock 4 input report (Bluetooth HID). Pure logic, testable on the PC.
 *
 * Bluetooth frames start with 0xA1 (HIDP DATA | INPUT) and then the report id:
 *   0x01: basic report, sent until full mode is requested. LX is at byte 2.
 *   0x11: full report (after GET_REPORT 0x02). Two extra header bytes, LX at byte 4.
 * After that the layout matches the USB report: LX LY RX RY, buttons x3, L2, R2.
 */
public final class DS4State {
    public final double lx, ly, rx, ry; // -1..1, up is negative
    public final double l2, r2;         // 0..1
    public final int dpad;              // 0..7 clockwise from up, 8 = released
    public final boolean square, cross, circle, triangle;
    public final boolean l1, r1, share, options, l3, r3, ps, touchpad;

    private DS4State(byte[] b, int o) {
        lx = axis(b[o + 1]);
        ly = axis(b[o + 2]);
        rx = axis(b[o + 3]);
        ry = axis(b[o + 4]);
        int b1 = b[o + 5] & 0xFF;
        int b2 = b[o + 6] & 0xFF;
        int b3 = b[o + 7] & 0xFF;
        dpad = b1 & 0x0F;
        square = (b1 & 0x10) != 0;
        cross = (b1 & 0x20) != 0;
        circle = (b1 & 0x40) != 0;
        triangle = (b1 & 0x80) != 0;
        l1 = (b2 & 0x01) != 0;
        r1 = (b2 & 0x02) != 0;
        share = (b2 & 0x10) != 0;
        options = (b2 & 0x20) != 0;
        l3 = (b2 & 0x40) != 0;
        r3 = (b2 & 0x80) != 0;
        ps = (b3 & 0x01) != 0;
        touchpad = (b3 & 0x02) != 0;
        l2 = (b[o + 8] & 0xFF) / 255.0;
        r2 = (b[o + 9] & 0xFF) / 255.0;
    }

    /** Returns null for frames that aren't DS4 input reports 0x01 or 0x11. */
    public static DS4State parse(byte[] buf, int len) {
        if (len < 2 || (buf[0] & 0xFF) != 0xA1) {
            return null;
        }
        int id = buf[1] & 0xFF;
        int off;
        if (id == 0x11) {
            off = 3;
        } else if (id == 0x01) {
            off = 1;
        } else {
            return null;
        }
        if (len < off + 10) {
            return null;
        }
        return new DS4State(buf, off);
    }

    private static double axis(byte v) {
        double d = ((v & 0xFF) - 127.5) / 127.5;
        return d < -1 ? -1 : (d > 1 ? 1 : d);
    }
}
