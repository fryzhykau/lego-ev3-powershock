"""One version for the whole app: VERSION, the changelog, the console and the brick's hello line."""
import os
import re
import socket
import time
import unittest
import zipfile

import ev3_brick
import ev3_console as c
import version

ROOT = version.ROOT


class VersionFileTest(unittest.TestCase):
    def test_version_is_semver(self):
        self.assertIsNotNone(version.parse(version.__version__), version.__version__)

    def test_changelog_has_this_version_first(self):
        with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("## [Unreleased]", text)
        releases = re.findall(r"^## \[(\d+\.\d+\.\d+[^\]]*)\] - \d{4}-\d{2}-\d{2}$", text, re.M)
        self.assertTrue(releases, "no dated releases in CHANGELOG.md")
        self.assertEqual(releases[0], version.__version__, "VERSION and the newest CHANGELOG entry differ")
        self.assertEqual(len(releases), len(set(releases)), "a version appears twice")
        ordered = sorted(releases, key=version.parse, reverse=True)
        self.assertEqual(releases, ordered, "releases must be newest first")

    def test_parse_orders_prereleases_first(self):
        self.assertLess(version.parse("0.8.0-beta"), version.parse("0.8.0"))
        self.assertLess(version.parse("0.7.9"), version.parse("0.8.0"))
        self.assertIsNone(version.parse("7"))
        self.assertIsNone(version.parse("v0.7.0"))

    def test_bad_file_is_reported_not_crashed(self):
        self.assertEqual(version.read(os.path.join(ROOT, "no-such-file")), "0.0.0-unknown")


class JarVersionTest(unittest.TestCase):
    def test_reads_stamp_from_jar(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "__test_stamp.jar")
        try:
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("powershock/version.txt", "1.2.3\n")
            self.assertEqual(ev3_brick.jar_version(path), "1.2.3")
        finally:
            os.remove(path)

    def test_missing_jar_or_stamp(self):
        self.assertIsNone(ev3_brick.jar_version(os.path.join(ROOT, "no-such.jar")))


class HelloLineTest(unittest.TestCase):
    def setUp(self):
        self.link = c.Link()

    def tearDown(self):
        self.link.disconnect()

    def _brick(self, hello):
        """A stand-in receiver that sends `hello` (or nothing) and then status lines."""
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        old, c.EV3_PORT = c.EV3_PORT, srv.getsockname()[1]
        self.addCleanup(setattr, c, "EV3_PORT", old)
        self.assertTrue(self.link.connect("127.0.0.1"))
        conn, _ = srv.accept()
        srv.close()
        self.addCleanup(conn.close)
        if hello:
            conn.sendall(hello)
        conn.sendall(b"T 8.00 0.1 0.0 A=0:0 B=0:0 C=0:0 D=0:0 1=0:0 2=0:0 3=0:0 4=0:0\n")
        for _ in range(30):
            time.sleep(0.05)
            if self.link.status()["telemetry"]:
                break
        return self.link.status()

    def test_brick_version_is_recorded(self):
        self.assertEqual(self._brick(b"V 0.7.0\n")["brickVersion"], "0.7.0")

    def test_old_brick_without_hello(self):
        st = self._brick(None)
        self.assertIsNotNone(st["telemetry"])
        self.assertIsNone(st["brickVersion"])

    def test_practice_brick_says_its_version(self):
        fake = c.FakeEV3()
        err = fake.start()
        if err:
            self.skipTest(err)
        self.addCleanup(fake.stop)
        self.assertTrue(self.link.connect("127.0.0.1"))
        for _ in range(40):
            time.sleep(0.05)
            if self.link.status()["brickVersion"]:
                break
        self.assertEqual(self.link.status()["brickVersion"], version.__version__)


if __name__ == "__main__":
    unittest.main()
