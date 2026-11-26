"""The privacy check itself, and a run over everything git would publish."""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
import privacy_check as pc  # noqa: E402


class PatternTest(unittest.TestCase):
    def msgs(self, text, terms=()):
        return [m for _, m in pc.check_text("x.py", text, list(terms))]

    def test_finds_real_addresses(self):
        # samples are split so this file passes its own check
        self.assertTrue(self.msgs("brick at 02:00:5E:" + "10:00:01"))
        self.assertTrue(self.msgs("got 203.0.113." + "7 from DHCP"))
        self.assertTrue(self.msgs("mail me: someone" + "@example.org"))

    def test_examples_are_fine(self):
        self.assertEqual(self.msgs("DS4_MAC = 00:00:00:00:00:00; ssh root@10.0.1.1; http://127.0.0.1:8765"), [])
        self.assertEqual(self.msgs("Co-Authored-By: Claude <noreply@anthropic.com>"), [])
        self.assertEqual(self.msgs("version 0.7.0, 1.2.3-beta and 1.2.3.4.5"), [])

    def test_finds_secrets(self):
        self.assertTrue(self.msgs("token ghp_" + "a" * 36))
        self.assertTrue(self.msgs("psk=" + "ab" * 32))
        self.assertTrue(self.msgs("-----BEGIN OPENSSH " + "PRIVATE KEY-----"))

    def test_finds_home_folders(self):
        self.assertTrue(self.msgs("C:" + "\\Users\\alice\\Documents"))
        self.assertEqual(self.msgs(r"%USERPROFILE%\.jdks and C:\Users\<you>"), [])

    def test_private_terms_case_insensitive(self):
        self.assertTrue(self.msgs("joined MyHomeWifi", ["myhomewifi"]))

    def test_forbidden_paths(self):
        bad = ["sd_lejos/x", "lib/rt7.jar", "out/powershock-wifi.jar", "pc/mapping.json", "docs/DEVICE_LOG.md",
               ".private-terms", "lejosimage.bz2"]
        for rel in bad:
            self.assertTrue(any(rx.search(rel) for rx, _ in pc.FORBIDDEN_PATHS), rel)
        self.assertFalse(any(rx.search("pc/ev3_console.py") for rx, _ in pc.FORBIDDEN_PATHS))


class RepositoryTest(unittest.TestCase):
    def test_nothing_private_would_be_published(self):
        try:
            files = pc.published_files()
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("not a git repository")
        self.assertEqual(pc.check(files), [])


if __name__ == "__main__":
    unittest.main()
