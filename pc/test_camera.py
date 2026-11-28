"""The robot camera: the Pi streamer (pi/powershock_cam.py) and the console's relay (camera.py)."""
import argparse
import io
import os
import sys
import tempfile
import threading
import time
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


def part(jpeg, size=None):
    n = len(jpeg) if size is None else size
    return b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(n).encode() + b"\r\n\r\n" + jpeg + b"\r\n"


class ReadPartsTest(unittest.TestCase):
    def test_parts_by_length(self):
        body = io.BytesIO(part(J1) + part(J2) + part(J1))
        self.assertEqual(list(camera.read_parts(body)), [J1, J2, J1])

    def test_cut_short(self):
        body = io.BytesIO(part(J1) + part(J2)[:-10])
        self.assertEqual(list(camera.read_parts(body)), [J1])

    def test_far_too_big_or_bad_length_stops(self):
        self.assertEqual(list(camera.read_parts(io.BytesIO(part(J1, camera.MAX_FRAME + 1)))), [])
        self.assertEqual(list(camera.read_parts(io.BytesIO(part(J1, 0)))), [])
        bad = io.BytesIO(b"Content-Length: lots\r\n\r\n" + J1 + b"\r\n" + part(J2))
        self.assertEqual(list(camera.read_parts(bad)), [J2])


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


class OpenSocketTest(unittest.TestCase):
    def test_a_name_windows_only_finds_one_family_at_a_time_still_connects(self):
        """Windows can fail a .local lookup for "either family" while answering for IPv4 alone."""
        import socket
        srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
        self.addCleanup(srv.close)
        port = srv.getsockname()[1]
        real = socket.getaddrinfo

        def lookup(host, prt, family=0, *a):
            if family == socket.AF_INET:
                return real("127.0.0.1", prt, family, *a)
            raise socket.gaierror(11001, "getaddrinfo failed")
        camera.socket.getaddrinfo = lookup
        self.addCleanup(setattr, camera.socket, "getaddrinfo", real)
        s = camera.open_socket("pi.local", port, 2)
        s.close()

    def test_no_address_at_all_raises(self):
        import socket
        real = socket.getaddrinfo

        def lookup(*a, **k):
            raise socket.gaierror(11001, "getaddrinfo failed")
        camera.socket.getaddrinfo = lookup
        self.addCleanup(setattr, camera.socket, "getaddrinfo", real)
        with self.assertRaises(OSError):
            camera.open_socket("pi.local", 8080, 1)


class FakePi:
    """The real Pi request handler, fed with two pretend frames."""

    def __init__(self):
        self.frames = pi.Frames()
        args = argparse.Namespace(width=640, height=480, fps=20, flip=False, settings={"colours": "normal"},
                                  settings_file=os.path.join(tempfile.mkdtemp(), "cam.json"))
        self.args = args
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

    def test_frames_come_one_at_a_time_and_free_the_slot(self):
        self.cam.set("127.0.0.1", self.pi.port, KEY)
        stop, got = threading.Event(), []
        for jpeg in self.cam.frames(stop):
            got.append(jpeg)
            if len(got) == 3:
                stop.set()
        self.assertTrue(all(j in (J1, J2) for j in got) and len(got) == 3, got)
        self.assertTrue(self.cam.streams.acquire(blocking=False))  # the slot was given back
        self.cam.streams.release()

    def test_frames_need_a_free_slot(self):
        self.cam.set("127.0.0.1", self.pi.port, KEY)
        for _ in range(camera.MAX_STREAMS):
            self.cam.streams.acquire()
        self.addCleanup(lambda: [self.cam.streams.release() for _ in range(camera.MAX_STREAMS)])
        with self.assertRaises(camera.CameraError):
            next(self.cam.frames(threading.Event()))

    def test_name_with_ipv6_too_connects_quickly(self):
        # "localhost" also resolves to ::1, where nothing listens: on Windows trying that first took ~2 s
        self.cam.set("localhost", self.pi.port, KEY)
        t = time.monotonic()
        st = self.cam.status(max_age=0)
        self.assertTrue(st["reachable"], st)
        self.assertLess(time.monotonic() - t, 1.0)

    def test_forget(self):
        self.cam.set("127.0.0.1", self.pi.port, KEY)
        self.cam.forget()
        self.assertFalse(os.path.exists(self.cfg))
        self.assertFalse(self.cam.configured())


class ColoursTest(unittest.TestCase):
    """A camera without an infrared filter looks pink or purple; its NoIR tuning fixes that."""

    def setUp(self):
        self.pi = FakePi()
        self.addCleanup(self.pi.close)
        self.cam = camera.Camera(os.path.join(tempfile.mkdtemp(), "camera.json"))
        self.cam.set("127.0.0.1", self.pi.port, KEY)

    def test_the_console_switches_the_pi_to_noir_and_it_keeps_the_choice(self):
        killed = []
        self.pi.frames.proc = type("P", (), {"kill": lambda _: killed.append(True)})()
        st = self.cam.set_colours("noir")
        self.assertEqual(st["colours"], "noir")
        self.assertEqual(killed, [True], "the camera tool restarts with the new setting")
        self.assertEqual(pi.load_settings(self.pi.args.settings_file), {"colours": "noir"})
        self.assertEqual(self.cam.status(max_age=0)["colours"], "noir")
        self.cam.set_colours("normal")
        self.assertEqual(pi.load_settings(self.pi.args.settings_file), {"colours": "normal"})

    def test_only_known_colours_are_taken(self):
        with self.assertRaises(camera.CameraError):
            self.cam.set_colours("purple")
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.pi.port, timeout=5)
        conn.request("POST", "/settings", body=b'{"colours": "x"}', headers={"X-PowerShock-Key": KEY})
        self.assertEqual(conn.getresponse().status, 400)
        conn.close()
        conn = http.client.HTTPConnection("127.0.0.1", self.pi.port, timeout=5)
        conn.request("POST", "/settings", body=b'{"colours": "noir"}', headers={"X-PowerShock-Key": "wrong" * 4})
        self.assertEqual(conn.getresponse().status, 403, "the key is needed to change settings too")
        conn.close()
        self.assertEqual(self.pi.args.settings["colours"], "normal")

    def test_a_missing_or_broken_settings_file_means_normal(self):
        d = tempfile.mkdtemp()
        self.assertEqual(pi.load_settings(os.path.join(d, "none.json")), {"colours": "normal"})
        bad = os.path.join(d, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write('["noir"]')
        self.assertEqual(pi.load_settings(bad), {"colours": "normal"})

    def test_noir_uses_the_cameras_own_noir_tuning(self):
        d = tempfile.mkdtemp()
        open(os.path.join(d, "ov5647_noir.json"), "w").close()
        tuning = pi.noir_tuning("ov5647", dirs=(os.path.join(d, "missing"), d))
        self.assertEqual(tuning, os.path.join(d, "ov5647_noir.json"))
        self.assertIsNone(pi.noir_tuning("imx219", dirs=(d,)))
        self.assertIsNone(pi.noir_tuning(None, dirs=(d,)))
        real = pi.shutil.which
        pi.shutil.which = lambda tool: "/usr/bin/" + tool
        self.addCleanup(setattr, pi.shutil, "which", real)
        cmds = pi.camera_commands(640, 480, 20, False, 70, tuning, True)
        self.assertEqual(cmds[0][-2:], ["--tuning-file", tuning])
        self.assertEqual(cmds[-1][-2:], ["-awb", "greyworld"], "raspivid has no tuning files")
        plain = pi.camera_commands(640, 480, 20, False, 70)
        self.assertNotIn("--tuning-file", plain[0])
        self.assertNotIn("greyworld", plain[-1])


if __name__ == "__main__":
    unittest.main()
