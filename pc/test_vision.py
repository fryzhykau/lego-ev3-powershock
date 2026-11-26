"""Object recognition (pc/vision.py) and its model download (pc/tools/get_model.py).

The parts that need numpy, onnxruntime, Pillow or the model file are skipped when those aren't
installed, so the tests still pass on a plain Python.
"""
import argparse
import hashlib
import importlib.util
import io
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import camera
import vision

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pi"))
sys.path.insert(0, os.path.join(HERE, "tools"))
import get_model  # noqa: E402
import powershock_cam as pi  # noqa: E402

HAVE_NUMPY = importlib.util.find_spec("numpy") is not None
HAVE_ALL = all(importlib.util.find_spec(m) is not None for m, _ in vision.PACKAGES)
HAVE_MODEL = HAVE_ALL and os.path.isfile(vision.MODEL)
KEY = "k" * 24


def jpeg(color=(90, 120, 140), disc=True):
    """A real JPEG: a plain background with a red disc (the model calls it a frisbee)."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (640, 480), color)
    if disc:
        ImageDraw.Draw(im).ellipse((250, 150, 400, 300), fill=(220, 60, 40))
    b = io.BytesIO()
    im.save(b, "JPEG")
    return b.getvalue()


class LabelsTest(unittest.TestCase):
    def test_eighty_kinds(self):
        self.assertEqual(len(vision.LABELS), 80)
        self.assertEqual(len(set(vision.LABELS)), 80)
        self.assertEqual(vision.LABELS[0], "person")


class MissingTest(unittest.TestCase):
    def test_no_model_file(self):
        v = vision.Vision(camera.Camera(os.path.join(tempfile.mkdtemp(), "camera.json")), model="nowhere.onnx")
        st = v.status()
        self.assertFalse(st["available"])
        self.assertIn("model", st["missing"])
        self.assertIn("get_model.py", st["setup"])
        r = v.poll(True)
        self.assertFalse(r["ok"])
        self.assertIn("setup", r["error"])
        self.assertIsNone(v.worker)  # nothing started

    def test_wrong_model_file_is_refused(self):
        bad = os.path.join(tempfile.mkdtemp(), "m.onnx")
        with open(bad, "wb") as f:
            f.write(b"not a model")
        with self.assertRaises(vision.VisionError) as cm:
            vision.Detector(bad)
        self.assertIn("isn't the one", str(cm.exception))


@unittest.skipUnless(HAVE_NUMPY, "numpy isn't installed")
class DecodeTest(unittest.TestCase):
    def setUp(self):
        import numpy as np
        self.np = np
        self.grids, self.strides = vision.make_grids(416)
        self.out = np.zeros((len(self.grids), 85), np.float32)

    def put(self, row, cls, score, dx=0.0):
        """A thing centred on grid cell `row`, 4 cells across, at stride 8."""
        self.out[row, :4] = [0.5 + dx, 0.5, self.np.log(4.0), self.np.log(4.0)]
        self.out[row, 4] = 1.0
        self.out[row, 5 + cls] = score

    def test_grids(self):
        self.assertEqual(len(self.grids), 52 * 52 + 26 * 26 + 13 * 13)
        self.assertEqual(self.strides[0, 0], 8)
        self.assertEqual(self.strides[-1, 0], 32)
        self.assertEqual(list(self.grids[53]), [1, 1])

    def test_box_comes_back_as_fractions_of_the_picture(self):
        self.put(52 * 10 + 20, 0, 0.9)  # cell x 20, y 10: centre (164, 84), 32 px wide
        items = vision.decode(self.out, self.grids, self.strides, 0.5, 832, 832)
        self.assertEqual(len(items), 1)
        t = items[0]
        self.assertEqual((t["label"], t["score"]), ("person", 0.9))
        # /0.5 for the scale: centre (328, 168), 64 px: (296, 136)-(360, 200) on 832 px
        for got, want in zip(t["box"], [296 / 832, 136 / 832, 360 / 832, 200 / 832]):
            self.assertAlmostEqual(got, want, places=3)

    def test_weak_guesses_are_left_out(self):
        self.put(100, 0, 0.2)
        self.assertEqual(vision.decode(self.out, self.grids, self.strides, 1.0, 416, 416), [])

    def test_overlapping_boxes_of_one_thing_become_one(self):
        self.put(100, 41, 0.9)
        self.put(101, 41, 0.7, dx=-0.9)  # nearly the same place, same kind
        self.put(102, 0, 0.8, dx=-1.9)  # same place, another kind: kept
        items = vision.decode(self.out, self.grids, self.strides, 1.0, 416, 416)
        self.assertEqual([(t["label"], t["score"]) for t in items], [("cup", 0.9), ("person", 0.8)])

    def test_nms_keeps_separate_boxes(self):
        np = self.np
        boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], np.float32)
        self.assertEqual(vision.nms(boxes, np.array([0.9, 0.8, 0.7])), [0, 2])


@unittest.skipUnless(HAVE_MODEL, "numpy, onnxruntime, Pillow or the model file isn't here")
class DetectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.det = vision.Detector()

    def test_prepare_fits_the_picture_top_left(self):
        x, r, w, h, full = self.det.prepare(jpeg())
        self.assertEqual(x.shape, (1, 3, 416, 416))
        self.assertEqual(full, (640, 480))
        self.assertAlmostEqual(r, 0.65)
        self.assertEqual(float(x[0, 0, 410, 10]), 114.0)  # grey padding below the picture
        self.assertAlmostEqual(float(x[0, 0, 10, 410]), 140, delta=6)  # the picture's blue, 416 wide (BGR)

    def test_finds_the_disc(self):
        items, size = self.det(jpeg())
        self.assertEqual(size, (640, 480))
        self.assertTrue(items, "expected the red disc to be found")
        x0, y0, x1, y1 = items[0]["box"]
        self.assertAlmostEqual((x0 + x1) / 2, 325 / 640, delta=0.05)
        self.assertAlmostEqual((y0 + y1) / 2, 225 / 480, delta=0.05)

    def test_bad_picture(self):
        with self.assertRaises(OSError):
            self.det(b"\xff\xd8 not really a jpeg \xff\xd9")


class FakePi:
    """The real Pi request handler, fed with the frames given."""

    def __init__(self, frames):
        self.frames = pi.Frames()
        args = argparse.Namespace(width=640, height=480, fps=20, flip=False)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), pi.make_handler(self.frames, KEY, args))
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]
        self.feeding = True
        threading.Thread(target=self._feed, args=(frames,), daemon=True).start()

    def _feed(self, frames):
        n = 0
        while self.feeding:
            self.frames.put(frames[n % len(frames)])
            n += 1
            time.sleep(0.03)

    def close(self):
        self.feeding = False
        self.srv.shutdown()
        self.srv.server_close()


def wait_for(cond, limit=10.0):
    t = time.monotonic()
    while time.monotonic() - t < limit:
        if cond():
            return True
        time.sleep(0.05)
    return False


@unittest.skipUnless(HAVE_MODEL, "numpy, onnxruntime, Pillow or the model file isn't here")
class VisionTest(unittest.TestCase):
    def start(self, frames):
        self.pi = FakePi(frames)
        self.addCleanup(self.pi.close)
        self.cam = camera.Camera(os.path.join(tempfile.mkdtemp(), "camera.json"))
        self.cam.set("127.0.0.1", self.pi.port, KEY)
        self.v = vision.Vision(self.cam)

    def test_runs_while_asked_and_stops_after(self):
        self.start([jpeg()])
        self.assertTrue(self.v.poll(True)["ok"])
        self.assertTrue(wait_for(lambda: (self.v.poll(True).get("items") or [None])[0] is not None))
        r = self.v.poll(True)
        self.assertEqual(r["size"], [640, 480])
        self.assertLess(r["age"], 2)
        self.assertGreater(r["ms"], 0)
        self.assertEqual(self.v.poll(False), {"ok": True, "on": False})
        self.assertTrue(wait_for(lambda: self.v.worker is None, 3))
        # the camera view slot is given back
        self.assertTrue(wait_for(lambda: self.cam.streams._value == camera.MAX_STREAMS, 7))

    def test_stops_by_itself_when_the_page_stops_asking(self):
        self.start([jpeg()])
        self.v.poll(True)
        with self.v.lock:
            self.v.until = time.monotonic() + 0.3
        self.assertTrue(wait_for(lambda: self.v.worker is None, 3))

    def test_bad_frames_are_skipped(self):
        self.start([b"\xff\xd8 junk \xff\xd9", jpeg()])
        self.v.poll(True)
        self.assertTrue(wait_for(lambda: self.v.poll(True).get("items")))
        self.v.poll(False)

    def test_a_frame_from_an_earlier_run_is_not_used(self):
        self.start([jpeg()])
        self.pi.close()  # no new frames will come
        with self.v.lock:
            self.v.frame, self.v.seq = jpeg(), 7  # left over from an earlier run
        self.v.poll(True)
        self.assertTrue(wait_for(lambda: self.v.poll(True).get("error")))
        time.sleep(0.5)
        self.assertNotIn("items", self.v.poll(True))
        self.v.poll(False)

    def test_camera_off_is_explained(self):
        self.start([jpeg()])
        self.pi.close()
        self.v.poll(True)
        self.assertTrue(wait_for(lambda: self.v.poll(True).get("error")))
        self.assertIn("isn't answering", self.v.poll(True)["error"])
        self.v.poll(False)


class Serve(BaseHTTPRequestHandler):
    body = b""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *a):
        pass


class DownloadTest(unittest.TestCase):
    def setUp(self):
        Serve.body = b"model bytes " * 1000
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Serve)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/m.onnx"
        self.dir = tempfile.mkdtemp()
        self.dest = os.path.join(self.dir, "models", "m.onnx")

    def test_good_download_is_kept(self):
        get_model.download(self.url, self.dest, hashlib.sha256(Serve.body).hexdigest(), len(Serve.body), progress=False)
        with open(self.dest, "rb") as f:
            self.assertEqual(f.read(), Serve.body)
        self.assertEqual(os.listdir(os.path.dirname(self.dest)), ["m.onnx"])

    def test_wrong_checksum_is_refused_and_nothing_left_behind(self):
        with self.assertRaises(ValueError):
            get_model.download(self.url, self.dest, "0" * 64, len(Serve.body), progress=False)
        self.assertEqual(os.listdir(os.path.dirname(self.dest)), [])

    def test_oversized_download_is_refused(self):
        with self.assertRaises(ValueError):
            get_model.download(self.url, self.dest, hashlib.sha256(Serve.body).hexdigest(), 100, progress=False)
        self.assertFalse(os.path.exists(self.dest))


if __name__ == "__main__":
    unittest.main()
