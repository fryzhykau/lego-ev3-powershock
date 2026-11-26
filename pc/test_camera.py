"""The robot camera: the Pi streamer (pi/powershock_cam.py) and the console's relay (camera.py)."""
import argparse
import io
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

import camera

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pi"))
import powershock_cam as pi  # noqa: E402

# smallest useful stand-ins for JPEGs: start and end markers around some bytes
J1 = b"\xff\xd8" + b"one" + b"\xff\xd9"
J2 = b"\xff\xd8" + b"two!" + b"\xff\xd9"
KEY = "k" * 24


class SplitTest(unittest.TestCase):
    def test_whole_frames_come_off_the_front(self):
        frames, rest = pi.split_jpegs(b"junk" + J1 + J2 + b"\xff\xd8part")
        self.assertEqual(frames, [J1, J2])
        self.assertEqual(rest, b"\xff\xd8part")

    def test_frame_split_across_reads(self):
        frames, rest = pi.split_jpegs(J1[:4])
        self.assertEqual(frames, [])
        frames, rest = pi.split_jpegs(rest + J1[4:])
        self.assertEqual(frames, [J1])
        self.assertEqual(rest, b"")

    def test_runaway_frame_is_dropped(self):
        _, rest = pi.split_jpegs(b"\xff\xd8" + b"x" * (pi.MAX_FRAME + 10))
        self.assertEqual(rest, b"")


class KeyTest(unittest.TestCase):
    def test_key_is_made_once_and_kept(self):
        path = os.path.join(tempfile.mkdtemp(), "key")
        k = pi.load_key(path)
        self.assertGreaterEqual(len(k), 16)
        self.assertEqual(pi.load_key(path), k)
        self.assertRegex(k, camera.KEY_RE)


class CheckTest(unittest.TestCase):
    def test_good(self):
        self.assertEqual(camera.check(" raspberrypi.local ", "8080", KEY), ("raspberrypi.local", 8080, KEY))
        self.assertEqual(camera.check("192.168.1.40", 8080, KEY)[0], "192.168.1.40")

    def test_bad(self):
        for host, port, key in [("http://x", 8080, KEY), ("a/b", 8080, KEY), ("a..b", 8080, KEY), ("", 8080, KEY),
                                ("pi", 0, KEY), ("pi", "x", KEY), ("pi", 8080, "short"), ("pi", 8080, "bad key with spaces!!")]:
            with self.assertRaises(camera.CameraError, msg=(host, port, key)):
                camera.check(host, port, key)


class FakePi:
    """The real Pi request handler, fed with two pretend frames."""

    def __init__(self):
        self.frames = pi.Frames()
        args = argparse.Namespace(width=640, height=480, fps=20, flip=False)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), pi.make_handler(self.frames, KEY, args))
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]
        self.feeding = True
        threading.Thread(target=self._feed, daemon=True).start()

    def _feed(self):
        n = 0
        while self.feeding:
            self.frames.put(J1 if n % 2 == 0 else J2)
            n += 1
            threading.Event().wait(0.02)

    def close(self):
        self.feeding = False
        self.srv.shutdown()
        self.srv.server_close()


class LimitedWriter(io.BytesIO):
    """Takes a few frames, then acts like a closed page."""

    def write(self, b):
        if self.tell() > 2000:
            raise ConnectionResetError("page closed")
        return super().write(b)


class CameraTest(unittest.TestCase):
    def setUp(self):
        self.pi = FakePi()
        self.addCleanup(self.pi.close)
        self.cfg = os.path.join(tempfile.mkdtemp(), "camera.json")
        self.cam = camera.Camera(self.cfg)

    def test_not_set_up(self):
        self.assertEqual(self.cam.status(), {"configured": False})
        with self.assertRaises(camera.CameraError):
            self.cam.snapshot()

    def test_status_snapshot_and_saved_settings(self):
        self.cam.set("127.0.0.1", self.pi.port, KEY)
        st = self.cam.status(max_age=0)
        self.assertTrue(st["reachable"] and st["ok"], st)
        self.assertEqual((st["width"], st["height"]), (640, 480))
        self.assertIn(self.cam.snapshot(), (J1, J2))
        again = camera.Camera(self.cfg)  # settings survive a restart
        self.assertEqual((again.host, again.port, again.key), ("127.0.0.1", self.pi.port, KEY))
        self.cam.set("127.0.0.1", self.pi.port, "")  # an empty key keeps the saved one
        self.assertEqual(self.cam.key, KEY)

    def test_wrong_key_is_explained(self):
        self.cam.set("127.0.0.1", self.pi.port, "x" * 20)
        st = self.cam.status(max_age=0)
        self.assertFalse(st["reachable"])
        self.assertIn("key", st["error"])

    def test_relay_copies_video_until_the_page_closes(self):
        self.cam.set("127.0.0.1", self.pi.port, KEY)
        out, types = LimitedWriter(), []
        self.cam.relay(out, types.append)
        self.assertTrue(types[0].startswith("multipart/x-mixed-replace"))
        data = out.getvalue()
        self.assertIn(b"Content-Type: image/jpeg", data)
        self.assertTrue(J1 in data or J2 in data)
        self.assertTrue(self.cam.streams.acquire(blocking=False))  # the slot was given back
        self.cam.streams.release()

    def test_camera_off(self):
        port = self.pi.port
        self.pi.close()
        self.cam.set("127.0.0.1", port, KEY)
        st = self.cam.status(max_age=0)
        self.assertFalse(st["reachable"])
        self.assertIn("isn't answering", st["error"])

    def test_forget(self):
        self.cam.set("127.0.0.1", self.pi.port, KEY)
        self.cam.forget()
        self.assertFalse(os.path.exists(self.cfg))
        self.assertFalse(self.cam.configured())


if __name__ == "__main__":
    unittest.main()
