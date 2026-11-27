"""Free floor from the camera (pc/floor.py), what the map makes of it, and where the camera sits."""
import importlib.util
import io
import math
import os
import tempfile
import time
import unittest

import ev3_console as c
import floor as f
import vision
import worldmap as w

FLOOR, BOX = (190, 185, 170), (60, 90, 150)
HAVE_PIL = importlib.util.find_spec("PIL") is not None


def picture(box=None, colour=BOX, base=FLOOR, w_=f.W, h=f.H, shade=None, pattern=False):
    """A plain floor; box = (x0, x1, bottom row) is something standing on it, reaching the top.
    shade = (x0, x1, y0, y1) is a shadow on the floor."""
    px = []
    for y in range(h):
        for x in range(w_):
            p = base
            if pattern and (x // 3 + y // 3) % 2:
                p = (90, 40, 30)
            if shade and shade[0] <= x < shade[1] and shade[2] <= y < shade[3]:
                p = tuple(int(v * 0.65) for v in p)
            if box and box[0] <= x < box[1] and y < box[2]:
                p = colour
            px.append(p)
    return f.Picture(w_, h, px)


class ScannerTest(unittest.TestCase):
    def setUp(self):
        self.s = f.Scanner()

    def test_plain_floor_is_free_everywhere(self):
        r = self.s.scan(picture())
        self.assertEqual(r["cols"], [None] * f.COLS)
        self.assertEqual(r["quality"], 1.0)

    def test_finds_where_a_box_stands(self):
        r = self.s.scan(picture(box=(24, 40, 30)))
        cols = r["cols"]
        self.assertTrue(all(e is None for e in cols[:10] + cols[22:]))
        for e in cols[13:19]:
            self.assertAlmostEqual(e, 30 / f.H, delta=0.03)

    def test_a_shadow_is_still_floor(self):
        r = self.s.scan(picture(shade=(10, 50, 20, 40)))
        self.assertEqual(r["cols"], [None] * f.COLS)

    def test_a_box_right_in_front_is_not_taken_for_the_floor(self):
        self.s.scan(picture())  # the floor's look is learned
        for _ in range(20):
            r = self.s.scan(picture(box=(0, f.W, f.H)))  # then the box fills the whole picture
        self.assertTrue(all(e == 1.0 for e in r["cols"]), r["cols"])

    def test_lighting_changes_are_followed(self):
        self.s.scan(picture())
        dim = tuple(int(v * 0.8) for v in FLOOR)
        for _ in range(30):
            r = self.s.scan(picture(base=dim))
        self.assertEqual(r["cols"], [None] * f.COLS)
        self.assertLess(self.s.ref[2], sum(FLOOR) * 0.9)

    def test_patterned_floor_has_low_quality(self):
        self.assertLess(self.s.scan(picture(pattern=True))["quality"], w.CAM_QUALITY)

    def test_one_odd_column_is_noise(self):
        r = self.s.scan(picture(box=(30, 32, 30)))  # a single thin column
        self.assertEqual(r["cols"], [None] * f.COLS)

    @unittest.skipUnless(HAVE_PIL, "Pillow isn't installed")
    def test_from_jpeg(self):
        from PIL import Image
        im = Image.new("RGB", (640, 480), FLOOR)
        im.paste(BOX, (300, 0, 400, 240))
        b = io.BytesIO()
        im.save(b, "JPEG")
        pic = f.from_jpeg(b.getvalue())
        self.assertEqual((pic.w, pic.h, len(pic.pixels)), (f.W, f.H, f.W * f.H))
        r = self.s.scan(pic)
        self.assertAlmostEqual(r["cols"][f.COLS // 2], 0.5, delta=0.05)


class GroundTest(unittest.TestCase):
    def test_row_to_distance(self):
        r = dict(w.ROBOT)  # 15 cm up, looking 15 degrees down
        _, vfov = w.cam_angles(r)
        y = 0.5 + (math.atan(15 / 60) - math.radians(15)) / vfov
        self.assertAlmostEqual(w.ground(y, r), 60, delta=0.1)
        self.assertIsNone(w.ground(0.0, r))  # the top of the picture is above the horizon
        self.assertLess(w.ground(1.0, r), 20)  # the bottom is just in front

    def test_fit_finds_tilt_and_height(self):
        _, vfov = w.cam_angles(w.ROBOT)
        tilt, h = math.radians(22), 11.0
        pts = [(d, 0.5 + (math.atan(h / d) - tilt) / vfov) for d in (15, 25, 40, 60)]
        t, hh, err = w.fit_camera(pts, vfov)
        self.assertAlmostEqual(math.degrees(t), 22, delta=0.3)
        self.assertAlmostEqual(hh, 11, delta=0.3)
        self.assertLess(err, 0.01)
        t, hh, _ = w.fit_camera(pts, vfov, height=11.0)  # height known: tilt only
        self.assertAlmostEqual(math.degrees(t), 22, delta=0.3)


class SurroundTest(unittest.TestCase):
    """The practice room through the pretend camera, into the map."""

    def setUp(self):
        self.m = w.WorldMap(os.path.join(tempfile.mkdtemp(), "worldmap.json"))
        self.s = f.Scanner()

    def look(self, x, now=100.0):
        with self.m.lock:
            self.m.odo.x = float(x)
        self.m.surround(self.s.scan(c.practice_view(x, 0, 0)), now=now)
        return self.m.camera_now(now)

    def test_box_ahead(self):
        # the box's near side is at x = 70; the camera is 4 cm ahead of the axle
        for x in (0, 20, 40):
            v = self.look(x)
            self.assertTrue(v["good"])
            self.assertAlmostEqual(v["dist"], 66 - x, delta=3)
            self.assertAlmostEqual(v["at"], 100 - w.CAM_LATENCY)

    def test_into_the_map(self):
        for n in range(3):
            self.look(0, now=100 + n)
        hits = {(i, j) for i, j, _ in self.m.grid.cells()}
        self.assertTrue(hits & {(17, 0), (18, 0)}, hits)  # the box's front, at x = 70
        self.assertFalse(any(i < 15 and abs(j) < 3 for i, j in hits))  # nothing in the free floor before it

    def test_shown_on_the_map(self):
        now = time.monotonic()
        self.look(0, now=now)
        v = self.m.snapshot()["view"]
        self.assertEqual(len(v["pts"]), f.COLS)
        mid = v["pts"][f.COLS // 2]
        self.assertAlmostEqual(mid[2], 70, delta=3)  # where the floor ends, in map coordinates
        self.assertEqual(mid[4], 1)

    def test_patterned_floor_is_not_used(self):
        self.m.surround(self.s.scan(picture(pattern=True)), now=100)
        self.assertFalse(self.m.camera_now(100)["good"])
        self.assertEqual(self.m.grid.cells(), [])

    def test_stops_when_asked(self):
        self.look(0)
        self.m.end_view()
        self.assertIsNone(self.m.camera_now(100))

    def test_person_ahead_is_careful(self):
        with self.m.lock:
            self.m.objects = [{"label": "person", "x": 80.0, "y": 10.0, "n": 3, "seen": 99.5, "miss": 0}]
        self.assertEqual(self.look(0)["careful"], "person")
        with self.m.lock:
            self.m.objects[0]["label"] = "chair"
        self.assertIsNone(self.look(0)["careful"])

    def test_works_out_where_the_camera_sits(self):
        """Standing still at several distances from the box, the infrared sensor and the camera
        together should find the practice camera's real height and tilt."""
        self.m.set_robot(dict(w.ROBOT, camTilt=35, camHeight=300))  # both set wrong
        r = w.ROBOT
        for n, x in enumerate((0, 10, 20, 30, 40)):
            ir, _ = c.practice_sensors(x, 0, 0)
            with self.m.lock:
                self.m.eye = {"dist": ir * w.IR_RANGE / 100, "hit": True, "kind": "ir", "at": 100.0 + n, "speed": 0.0}
            # the scan comes from the true camera; the map turns it into distances with the wrong settings
            with self.m.lock:
                self.m.odo.x = float(x)
            self.m.surround(self.s.scan(c.practice_view(x, 0, 0)), now=100.0 + n)
        p = self.m.placement()
        self.assertTrue(p["ready"], p)
        self.assertAlmostEqual(p["tilt"], r["camTilt"], delta=2)
        self.assertAlmostEqual(p["height"], r["camHeight"], delta=25)
        self.m.forget_placement()
        self.assertEqual(self.m.placement()["samples"], 0)

    def test_no_samples_while_moving(self):
        with self.m.lock:
            self.m.eye = {"dist": 40.0, "hit": True, "kind": "ir", "at": 100.0, "speed": 0.0}
            self.m.speed = 20.0
        self.look(26)
        self.assertEqual(self.m.placement()["samples"], 0)


class WatchTest(unittest.TestCase):
    """The free-floor scan in the vision worker, fed by the practice camera: no Pi or Pillow needed."""

    def test_scans_while_asked_and_says_when_it_stops(self):
        got = []
        v = vision.Vision(None, model="nowhere.onnx", on_floor=got.append, practice=lambda: c.practice_view(0, 0, 0))
        r = v.watch_floor()
        self.assertTrue(r["ok"])
        t = time.monotonic()
        while not v.watch_floor().get("cols") and time.monotonic() - t < 5:
            time.sleep(0.05)
        r = v.watch_floor()
        self.assertEqual(r["source"], "practice")
        self.assertEqual(len(r["cols"]), f.COLS)
        self.assertTrue(got and got[-1]["cols"])
        with v.lock:
            v.floor_until = time.monotonic() + 0.2
        t = time.monotonic()
        while v.worker is not None and time.monotonic() - t < 3:
            time.sleep(0.05)
        self.assertIsNone(v.worker)
        time.sleep(0.1)
        self.assertIsNone(got[-1], "the map is told the scan stopped")


if __name__ == "__main__":
    unittest.main()
