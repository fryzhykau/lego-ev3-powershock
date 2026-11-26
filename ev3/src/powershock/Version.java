package powershock;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;

/** PowerShock's version, stamped into the jar by build.ps1 (from the VERSION file). */
final class Version {
    private static String value;

    private Version() {
    }

    static synchronized String get() {
        if (value == null) {
            value = "dev";
            try {
                InputStream in = Version.class.getResourceAsStream("version.txt");
                if (in != null) {
                    try {
                        String v = new BufferedReader(new InputStreamReader(in, "US-ASCII")).readLine();
                        if (v != null && v.trim().length() > 0 && v.trim().length() <= 32) {
                            value = v.trim();
                        }
                    } finally {
                        in.close();
                    }
                }
            } catch (Exception ignored) {
                // keep "dev"
            }
        }
        return value;
    }
}
