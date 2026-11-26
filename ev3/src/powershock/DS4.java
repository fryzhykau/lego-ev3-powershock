package powershock;

import com.sun.jna.Library;
import com.sun.jna.Native;

/**
 * Minimal DualShock 4 Bluetooth driver for leJOS EV3.
 *
 * Opens the two HID L2CAP channels to the controller itself (control PSM 0x11,
 * interrupt PSM 0x13) through libc via JNA, the way ds4drv does on Linux, so the
 * system Bluetooth stack's HID support isn't needed. The DS4 isn't paired with the
 * EV3, so it must be in pairing mode (hold Share + PS until the light bar flashes
 * fast) each time before connecting.
 */
public final class DS4 {
    private static final int AF_BLUETOOTH = 31;
    private static final int SOCK_SEQPACKET = 5;
    private static final int BTPROTO_L2CAP = 0;
    private static final int SOL_SOCKET = 1;
    private static final int SO_RCVTIMEO = 20;
    private static final int EAGAIN = 11;

    private static final int PSM_CONTROL = 0x11;
    private static final int PSM_INTERRUPT = 0x13;

    /** HIDP GET_REPORT (0x40) | feature (0x03), report 0x02: switches the DS4 to full 0x11 reports. */
    private static final byte[] REQUEST_FULL_MODE = {0x43, 0x02};

    interface LibC extends Library {
        int socket(int domain, int type, int protocol);
        int connect(int fd, byte[] addr, int len);
        int read(int fd, byte[] buf, int len);
        int write(int fd, byte[] buf, int len);
        int setsockopt(int fd, int level, int name, byte[] val, int len);
        int close(int fd);
    }

    private static final LibC C = (LibC) Native.loadLibrary("c", LibC.class);

    private final byte[] mac;
    private int ctl = -1;
    private int intr = -1;
    private final byte[] buf = new byte[128];

    /** @param mac "AA:BB:CC:DD:EE:FF" */
    public DS4(String mac) {
        this.mac = parseMac(mac);
    }

    /** Opens both channels and requests full reports. Throws with errno on failure. */
    public void connect() throws DS4Exception {
        close();
        ctl = open(PSM_CONTROL);
        intr = open(PSM_INTERRUPT);
        setReadTimeout(intr, 100);
        setReadTimeout(ctl, 100);
        if (C.write(ctl, REQUEST_FULL_MODE, REQUEST_FULL_MODE.length) < 0) {
            throw new DS4Exception("request full mode failed, errno " + Native.getLastError());
        }
        // Drain the feature-report reply so the control channel doesn't back up.
        C.read(ctl, buf, buf.length);
    }

    /**
     * Reads one input report. Returns null on timeout (100 ms) or a non-input frame.
     * Throws when the controller has disconnected.
     */
    public DS4State read() throws DS4Exception {
        int n = C.read(intr, buf, buf.length);
        if (n < 0) {
            int err = Native.getLastError();
            if (err == EAGAIN) {
                return null;
            }
            throw new DS4Exception("read failed, errno " + err);
        }
        if (n == 0) {
            throw new DS4Exception("controller disconnected");
        }
        return DS4State.parse(buf, n);
    }

    public void close() {
        if (intr >= 0) {
            C.close(intr);
            intr = -1;
        }
        if (ctl >= 0) {
            C.close(ctl);
            ctl = -1;
        }
    }

    private int open(int psm) throws DS4Exception {
        int fd = C.socket(AF_BLUETOOTH, SOCK_SEQPACKET, BTPROTO_L2CAP);
        if (fd < 0) {
            throw new DS4Exception("socket failed, errno " + Native.getLastError());
        }
        if (C.connect(fd, sockaddrL2(psm), 14) < 0) {
            int err = Native.getLastError();
            C.close(fd);
            throw new DS4Exception("connect psm 0x" + Integer.toHexString(psm) + " failed, errno " + err);
        }
        return fd;
    }

    /** struct sockaddr_l2 { u16 family; le16 psm; bdaddr_t bdaddr; le16 cid; u8 bdaddr_type; } padded to 14. */
    private byte[] sockaddrL2(int psm) {
        byte[] a = new byte[14];
        a[0] = (byte) AF_BLUETOOTH;
        a[1] = 0;
        a[2] = (byte) (psm & 0xFF);
        a[3] = (byte) (psm >> 8);
        System.arraycopy(mac, 0, a, 4, 6);
        return a; // cid = 0, bdaddr_type = 0 (BR/EDR)
    }

    private static void setReadTimeout(int fd, int ms) {
        // struct timeval { long tv_sec; long tv_usec; } — 32-bit ARM, little-endian
        int sec = ms / 1000;
        int usec = (ms % 1000) * 1000;
        byte[] tv = new byte[8];
        putLe32(tv, 0, sec);
        putLe32(tv, 4, usec);
        C.setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, tv, tv.length);
    }

    private static void putLe32(byte[] b, int o, int v) {
        b[o] = (byte) v;
        b[o + 1] = (byte) (v >> 8);
        b[o + 2] = (byte) (v >> 16);
        b[o + 3] = (byte) (v >> 24);
    }

    /** bdaddr_t stores the address bytes in reverse order. */
    static byte[] parseMac(String s) {
        String[] p = s.trim().split("[:-]");
        if (p.length != 6) {
            throw new IllegalArgumentException("bad MAC address: " + s);
        }
        byte[] b = new byte[6];
        for (int i = 0; i < 6; i++) {
            b[5 - i] = (byte) Integer.parseInt(p[i], 16);
        }
        return b;
    }

    public static final class DS4Exception extends Exception {
        private static final long serialVersionUID = 1L;

        public DS4Exception(String msg) {
            super(msg);
        }
    }
}
