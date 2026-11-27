package powershock;

import java.io.BufferedReader;
import java.io.FileReader;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Keeps the brick on the strongest saved WiFi network while it drives from room to room.
 *
 * wpa_supplicant only changes network when the current one is lost altogether; until then the
 * brick clings to a far router while a near one (or an extender) is in reach. This thread looks
 * at the signal every few seconds and, when it's weak and a saved network, or another access
 * point of the same network, is clearly stronger, switches to it. The same rule as the Pi's
 * pi/powershock_wifi.py (choose):
 *   - -60 dBm or better is good enough: never look for better;
 *   - below that, switch only to one at least 8 dB stronger;
 *   - after a switch, stay at least a minute, so it never flaps between two.
 *
 * Looking for networks takes the radio off its channel for a second or two: long enough to trip
 * the motors' 500 ms watchdog, and for the console to drop the link. So it only looks while the
 * robot stands still, at most every two minutes, and only with two or more saved networks to
 * choose between (on the real brick, a scan every 30 s dropped the link each time). A switch
 * drops the link for a few seconds; the motors stop (watchdog) and the console connects again.
 *
 * Also reports the signal for the status line: " w=-62" (dBm).
 */
final class WifiRoam implements Runnable {
    static final int GOOD = -60, MARGIN = 8;
    static final long HOLD_MS = 60000, CHECK_MS = 5000, RESCAN_MS = 120000, STILL_MS = 3000;

    private volatile String line = "";
    private volatile boolean running = true;
    private long lastSwitch = -HOLD_MS, lastScan = -RESCAN_MS;

    /** The signal for the status line, e.g. " w=-62" (empty without WiFi). */
    String telemetry() {
        return line;
    }

    void stop() {
        running = false;
    }

    public void run() {
        while (running) {
            try {
                step(System.currentTimeMillis());
            } catch (Throwable t) {
                // no WiFi, or wpa_cli missing: try again later
            }
            try {
                Thread.sleep(CHECK_MS);
            } catch (InterruptedException e) {
                return;
            }
        }
    }

    private void step(long now) throws Exception {
        int level = signal();
        line = level < 0 ? " w=" + level : "";
        if (level >= GOOD || level >= 0 || now - lastSwitch < HOLD_MS || now - lastScan < RESCAN_MS) {
            return;
        }
        if (now - DS4Receiver.movingAt < STILL_MS) {
            return; // scanning now would stall the driving link; wait until it stands still
        }
        Map<String, String> status = keyValues(wpa("status"));
        String bssid = status.get("bssid");
        if (bssid == null || !"COMPLETED".equals(status.get("wpa_state"))) {
            return; // not connected: wpa_supplicant picks a network itself
        }
        Map<String, String> saved = new HashMap<String, String>(); // ssid -> network id
        for (String l : wpa("list_networks")) {
            String[] p = l.split("\t");
            if (p.length >= 2 && !p[0].equals("network id")) {
                saved.put(p[1], p[0]);
            }
        }
        if (saved.size() < 2) {
            return; // nowhere else to go: don't stall the link for nothing
        }
        lastScan = now;
        wpa("scan");
        Thread.sleep(7000); // the WNA1100 dongle needs about 6 s to see every network
        String bestSsid = null, bestBssid = null;
        int best = Integer.MIN_VALUE, current = level;
        for (String l : wpa("scan_results")) {
            String[] p = l.split("\t"); // bssid, frequency, signal, flags, ssid
            if (p.length < 5 || !saved.containsKey(p[4])) {
                continue;
            }
            int sig;
            try {
                sig = Integer.parseInt(p[2].trim());
            } catch (NumberFormatException e) {
                continue;
            }
            if (p[0].equalsIgnoreCase(bssid)) {
                current = Math.max(current, sig);
            } else if (sig > best) {
                best = sig;
                bestSsid = p[4];
                bestBssid = p[0];
            }
        }
        if (bestBssid == null || current >= GOOD || best < current + MARGIN) {
            return;
        }
        lastSwitch = now;
        if (bestSsid.equals(status.get("ssid"))) {
            wpa("roam " + bestBssid); // another access point of the same network
        } else {
            wpa("select_network " + saved.get(bestSsid));
            Thread.sleep(15000);
            wpa("enable_network all"); // select_network turned the others off; the next switch needs them
        }
    }

    /** The signal in dBm from /proc/net/wireless, or 0 if there's no WiFi. */
    static int signal() {
        BufferedReader r = null;
        try {
            r = new BufferedReader(new FileReader("/proc/net/wireless"));
            String l;
            while ((l = r.readLine()) != null) {
                l = l.trim();
                if (l.startsWith("wlan0:")) {
                    String[] p = l.substring(6).trim().split("\\s+"); // status, link, level, noise...
                    if (p.length < 3) {
                        return 0;
                    }
                    int v = (int) Float.parseFloat(p[2]); // "-56." in dBm
                    return v > 0 ? v - 256 : v;            // some drivers count up from -256
                }
            }
        } catch (Exception e) {
            return 0;
        } finally {
            if (r != null) {
                try {
                    r.close();
                } catch (Exception ignored) {
                }
            }
        }
        return 0;
    }

    private static List<String> wpa(String args) throws Exception {
        Process p = Runtime.getRuntime().exec(new String[] {"sh", "-c", "wpa_cli -i wlan0 " + args});
        List<String> out = new ArrayList<String>();
        BufferedReader r = new BufferedReader(new InputStreamReader(p.getInputStream(), "UTF-8"));
        try {
            String l;
            while ((l = r.readLine()) != null) {
                out.add(l);
            }
        } finally {
            r.close();
            p.waitFor();
        }
        return out;
    }

    private static Map<String, String> keyValues(List<String> lines) {
        Map<String, String> out = new HashMap<String, String>();
        for (String l : lines) {
            int i = l.indexOf('=');
            if (i > 0) {
                out.put(l.substring(0, i), l.substring(i + 1));
            }
        }
        return out;
    }
}
