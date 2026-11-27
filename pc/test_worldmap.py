"""The live map: where the robot is (odometry), what it saw (grid), and the practice room."""
import math
import os
import tempfile
import time
import unittest

import brake
import ev3_brick
import ev3_console as c
import mapping
import worldmap as w

R = dict(w.ROBOT)
CM_PER_DEG = math.pi * R["wheel"] / 10 / 360


class LayoutTest(unittest.TestCase):
    def test_tank_preset(self):
        lay = w.layout(mapping.TANK)
        self.assertEqual(lay, {"type": "tank", "left": {"B": 1}, "right": {"C": 1}})

    def test_car_preset_uses_throttle_ports_and_steering(self):
        lay = w.layout(mapping.CAR)
        self.assertEqual(lay["type"], "car")
        self.assertEqual(lay["drive"], {"B": 1, "C": 1})
        self.assertEqual(lay["steer"], ("D", 1))

    def test_reversed_motor_counts_backwards(self):
        m = mapping.validate(dict(mapping.TANK, ports=dict(mapping.TANK["ports"], B=dict(mapping.TANK["ports"]["B"], invert=True))))
        self.assertEqual(w.layout(m)["left"], {"B": -1})

    def test_nothing_drives(self):
        self.assertIsNone(w.layout({"ports": {p: {"mode": "off"} for p in "ABCD"}}))


class OdometryTest(unittest.TestCase):
    def setUp(self):
        self.o = w.Odometry()

    def test_straight(self):
        tank = w.layout(mapping.TANK)
        self.o.update({"B": 0, "C": 0}, tank, R)
        self.o.update({"B": 360, "C": 360}, tank, R)
        self.assertAlmostEqual(self.o.x, 360 * CM_PER_DEG, places=3)
        self.assertAlmostEqual(self.o.y, 0.0, places=6)
        self.assertAlmostEqual(self.o.th, 0.0, places=6)

    def test_tank_spins_left_when_right_wheel_leads(self):
        tank = w.layout(mapping.TANK)
        self.o.update({"B": 0, "C": 0}, tank, R)
        self.o.update({"B": -100, "C": 100}, tank, R)
        expect = 2 * 100 * CM_PER_DEG / (R["track"] / 10)
        self.assertAlmostEqual(self.o.th, expect, places=6)
        self.assertAlmostEqual(math.hypot(self.o.x, self.o.y), 0.0, places=6)

    def test_car_steering_right_turns_clockwise(self):
        car = w.layout(mapping.CAR)
        self.o.update({"B": 0, "C": 0, "D": 20}, car, R)
        for k in range(1, 40):
            self.o.update({"B": 30 * k, "C": 30 * k, "D": 20}, car, R)
        self.assertLess(self.o.th, 0)
        self.assertLess(self.o.y, 0)  # drifted to the right

    def test_gyro_sets_the_heading(self):
        tank = w.layout(mapping.TANK)
        self.o.update({"B": 0, "C": 0}, tank, R, gyro=10)
        self.o.update({"B": 0, "C": 0}, tank, R, gyro=100)
        self.assertAlmostEqual(math.degrees(self.o.th), 90, places=6)

    def test_relink_doesnt_jump(self):
        tank = w.layout(mapping.TANK)
        self.o.update({"B": 5000, "C": 5000}, tank, R)
        self.o.relink()  # the brick restarted; its angles start from 0 again
        self.o.update({"B": 0, "C": 0}, tank, R)
        self.assertAlmostEqual(self.o.x, 0.0)


class GridTest(unittest.TestCase):
    def test_hit_marks_end_and_frees_the_way(self):
        g = w.Grid()
        for _ in range(3):
            g.ray(0, 0, 0, 40, True)
        cells = {(i, j): v for i, j, v in g.cells()}
        self.assertIn((10, 0), cells)  # 40 cm / 4 cm cells
        self.assertLess(g.lo[(g.half + 5) * g.size + g.half], 0)  # 20 cm along: free

    def test_no_hit_draws_nothing(self):
        g = w.Grid()
        g.ray(0, 0, 0, 70, False)
        self.assertEqual(g.cells(), [])

    def test_one_reading_isnt_a_wall_until_confirmed(self):
        g = w.Grid()
        g.ray(0, 0, 0, 40, True)
        g.ray(0, 0, 0, 70, False)  # next reading saw through it
        self.assertEqual(g.cells(), [])

    def test_outside_the_grid_is_ignored(self):
        g = w.Grid(size=11)
        g.ray(0, 0, 0, 500, True)
        g.paint(10000, 0, 3)
        self.assertEqual(g.floor, {})


class WorldMapTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.m = w.WorldMap(os.path.join(self.dir, "worldmap.json"))

    def tel(self, b, cc, ir=None, col=None):
        line = f"T 8.0 0.1 0.0 A=0:0 B=125:7 C=125:7 D=0:0 1=0:0 2=0:0 3=0:0 4=0:0 mB={b}:0:0:L mC={cc}:0:0:R"
        if col is not None:
            line += f" s3=col:{col}"
        if ir is not None:
            line += f" s4=ir:{ir}"
        return ev3_brick.parse_telemetry(line)

    def test_parse_sensor_readings(self):
        t = ev3_brick.parse_telemetry("T 8.0 0.1 0.0 A=0:0 B=0:0 C=0:0 D=0:0 1=0:0 2=0:0 3=0:0 4=0:0 s1=gy:-45 s2=us:123 s3=col:5 s4=ir:37 s5=ir:1 s2=zz:3")
        self.assertEqual(t["sensors"], {"S1": {"kind": "gy", "value": -45}, "S2": {"kind": "us", "value": 123},
                                        "S3": {"kind": "col", "value": 5}, "S4": {"kind": "ir", "value": 37}})

    def test_ir_draws_an_obstacle_ahead(self):
        for _ in range(3):
            self.m.feed(self.tel(0, 0, ir=50), mapping.TANK)  # 35 cm, from 6 cm ahead of the axle
        snap = self.m.snapshot()
        self.assertTrue(any(i == round(41 / 4) and j == 0 for i, j, _ in snap["cells"]), snap["cells"])
        self.assertEqual(snap["eye"]["hit"], True)

    def test_colour_paints_the_floor_and_trail_follows(self):
        self.m.feed(self.tel(0, 0, col=0), mapping.TANK)
        self.m.feed(self.tel(720, 720, col=2), mapping.TANK)
        snap = self.m.snapshot()
        colours = {c for _, _, c in snap["floor"]}
        self.assertEqual(colours, {0, 2})
        self.assertGreater(snap["pose"]["x"], 30)
        self.assertGreaterEqual(len(snap["trail"]), 2)

    def test_robot_settings_are_checked_and_saved(self):
        r = self.m.set_robot({"wheel": 5000, "track": "x", "gyroSign": -3, "evil": 1, "weight": -5})
        self.assertEqual(r["wheel"], 200)
        self.assertEqual(r["weight"], 0)
        self.assertEqual(w.robot_settings({"weight": "1250"})["weight"], 1250)
        self.assertEqual(r["track"], w.ROBOT["track"])
        self.assertEqual(r["gyroSign"], -1)
        self.assertNotIn("evil", r)
        self.assertEqual(w.WorldMap(self.m.config).robot["wheel"], 200)

    def test_reset_clears(self):
        for _ in range(3):
            self.m.feed(self.tel(0, 0, ir=50), mapping.TANK)
        self.m.reset()
        self.assertEqual(self.m.snapshot()["cells"], [])


class PracticeRoomTest(unittest.TestCase):
    def test_sensors_in_the_room(self):
        ir, col = c.practice_sensors(0, 0, 0)  # the box is 70 cm ahead of the axle, 64 cm from the eye
        self.assertLess(ir, w.IR_NOTHING)
        self.assertAlmostEqual(ir / 100 * w.IR_RANGE, 64, delta=1.5)
        self.assertEqual(col, 6)
        self.assertEqual(c.practice_sensors(0, 0, math.pi / 2)[0], 100)  # wall 84 cm from the eye: out of range
        self.assertLess(c.practice_sensors(0, 40, math.pi / 2)[0], w.IR_NOTHING)  # 44 cm: seen
        self.assertEqual(c.practice_sensors(118, 0, 0)[1], 2)  # blue tape

    def test_map_builds_from_the_practice_brick(self):
        fake = c.FakeEV3()
        err = fake.start()
        if err:
            self.skipTest(err)
        self.addCleanup(fake.stop)
        link = c.Link()
        self.addCleanup(link.disconnect)
        link.set_mapping(mapping.validate(mapping.CAR))
        self.assertTrue(link.connect("127.0.0.1"))
        for _ in range(40):
            time.sleep(0.1)
            if link.world.snapshot()["cells"]:
                break
        snap = link.world.snapshot()
        self.assertTrue(snap["cells"], "the box ahead should show up")
        self.assertTrue(all(14 <= i <= 18 for i, _, _ in snap["cells"]), snap["cells"])  # about 70 cm ahead


class SeeTest(unittest.TestCase):
    """Things the camera recognises, placed on the map from where they are in the picture."""

    def setUp(self):
        self.m = w.WorldMap(os.path.join(tempfile.mkdtemp(), "worldmap.json"))
        self.r = self.m.robot  # camera 4 cm ahead, 15 cm up, looking 15 degrees down, 62 degrees across

    def bottom_at(self, dist):
        """Where in the picture the bottom edge of something standing dist cm in front of the camera is."""
        r = self.r
        vfov = 2 * math.atan(math.tan(math.radians(r["camFov"]) / 2) * 3 / 4)
        down = math.atan(r["camHeight"] / 10 / dist)
        return 0.5 + (down - math.radians(r["camTilt"])) / vfov

    def item(self, label="chair", cx=0.5, dist=100.0, score=0.8):
        y1 = self.bottom_at(dist)
        return {"label": label, "score": score, "box": [cx - 0.05, y1 - 0.2, cx + 0.05, y1]}

    def test_shown_once_seen_twice(self):
        self.m.see([self.item()], now=1.0)
        self.assertEqual(self.m.snapshot()["objects"], [])  # one sighting may be a wrong guess
        self.m.see([self.item()], now=1.1)
        objs = self.m.snapshot()["objects"]
        self.assertEqual(len(objs), 1)
        self.assertEqual(objs[0]["label"], "chair")
        self.assertAlmostEqual(objs[0]["x"], 104, delta=1)  # 100 cm from the camera, which is 4 cm ahead
        self.assertAlmostEqual(objs[0]["y"], 0, delta=1)

    def test_left_of_the_picture_is_left_of_the_robot(self):
        for t in (1.0, 1.1):
            self.m.see([self.item(cx=0.2)], now=t)
        self.assertGreater(self.m.snapshot()["objects"][0]["y"], 20)

    def test_follows_the_robot(self):
        with self.m.lock:
            self.m.odo.x, self.m.odo.y, self.m.odo.th = 50.0, 20.0, math.pi / 2  # facing left
        for t in (1.0, 1.1):
            self.m.see([self.item(dist=60)], now=t)
        ob = self.m.snapshot()["objects"][0]
        self.assertAlmostEqual(ob["x"], 50, delta=1)
        self.assertAlmostEqual(ob["y"], 20 + 4 + 60, delta=1)

    def test_ir_distance_used_straight_ahead(self):
        with self.m.lock:
            self.m.eye = {"dist": 30.0, "hit": True, "kind": "ir", "at": 1.0, "speed": 0.0}
        for t in (1.0, 1.1):
            self.m.see([self.item(dist=100)], now=t)  # the picture says 100 cm; the IR sensor says 30
        self.assertAlmostEqual(self.m.snapshot()["objects"][0]["x"], 30 + 6, delta=1)  # the IR sensor is 6 cm ahead

    def test_unsure_or_in_the_air_is_left_out(self):
        for t in (1.0, 1.1):
            self.m.see([self.item(score=0.3), {"label": "clock", "score": 0.9, "box": [0.4, 0.05, 0.6, 0.15]}], now=t)  # above the horizon
        self.assertEqual(self.m.snapshot()["objects"], [])

    def test_two_of_a_kind_apart_stay_two(self):
        for t in (1.0, 1.1):
            self.m.see([self.item(cx=0.2), self.item(cx=0.8)], now=t)
        self.assertEqual(len(self.m.snapshot()["objects"]), 2)

    def test_gone_when_in_view_and_not_seen(self):
        for t in (1.0, 1.1):
            self.m.see([self.item(label="person")], now=t)
        for n in range(w.SEE_MISSES):
            self.m.see([], now=2 + n / 10)
        self.assertEqual(self.m.snapshot()["objects"], [])

    def test_kept_when_out_of_view(self):
        for t in (1.0, 1.1):
            self.m.see([self.item()], now=t)
        with self.m.lock:
            self.m.odo.th = math.pi  # turned round
        for n in range(w.SEE_MISSES + 5):
            self.m.see([], now=2 + n / 10)
        self.assertEqual(len(self.m.snapshot()["objects"]), 1)

    def test_cleared_with_the_map(self):
        for t in (1.0, 1.1):
            self.m.see([self.item()], now=t)
        self.m.reset()
        self.assertEqual(self.m.snapshot()["objects"], [])


class SpeedTest(unittest.TestCase):
    def test_forward_speed(self):
        self.assertAlmostEqual(w.forward_speed({"B": 360, "C": -360}, w.layout(mapping.TANK), R), 0.0)  # turning on the spot
        self.assertAlmostEqual(w.forward_speed({"B": -360, "C": -360}, w.layout(mapping.CAR), R), -360 * CM_PER_DEG)
        self.assertEqual(w.forward_speed({"B": 360}, None, R), 0.0)

    def test_speed_and_unplugged_sensor(self):
        m = w.WorldMap(os.path.join(tempfile.mkdtemp(), "worldmap.json"))
        tel = lambda deg, sensors: {"motors": {"B": {"tacho": deg, "speed": 360}, "C": {"tacho": deg, "speed": 360}},  # noqa: E731
                                    "sensors": sensors}
        ir = {"S4": {"kind": "ir", "value": 50}}
        for n in range(6):
            m.feed(tel(90 * n, ir), mapping.TANK, now=n * 0.25)
        m.feed(tel(540, ir), mapping.TANK, now=1.25)  # two lines arriving together don't look like a burst of speed
        eye, _ = m.eye_now()
        self.assertAlmostEqual(eye["speed"], 360 * CM_PER_DEG, delta=0.1)
        self.assertEqual(eye["at"], 1.25)
        m.feed(tel(450, {}), mapping.TANK, now=1.5)
        self.assertIsNone(m.eye_now()[0], "unplugged: no reading to brake on")

    def test_nearer_of_two_range_sensors(self):
        """Infrared and ultrasonic together: the brake gets the nearer obstacle, whichever port it's on."""
        m = w.WorldMap(os.path.join(tempfile.mkdtemp(), "worldmap.json"))
        tel = lambda sensors: {"motors": {"B": {"tacho": 0, "speed": 0}, "C": {"tacho": 0, "speed": 0}},  # noqa: E731
                               "sensors": sensors}
        m.feed(tel({"S2": {"kind": "us", "value": 25}, "S4": {"kind": "ir", "value": 99}}), mapping.TANK, now=1.0)
        eye = m.eye_now()[0]
        self.assertEqual((eye["kind"], eye["hit"], eye["dist"]), ("us", True, 25.0), "infrared sees nothing")
        m.feed(tel({"S1": {"kind": "ir", "value": 20}, "S2": {"kind": "us", "value": 80}}), mapping.TANK, now=1.25)
        eye = m.eye_now()[0]
        self.assertEqual((eye["kind"], eye["hit"], eye["dist"]), ("ir", True, 14.0), "infrared is nearer")
        m.feed(tel({"S2": {"kind": "us", "value": 255}, "S4": {"kind": "ir", "value": 99}}), mapping.TANK, now=1.5)
        self.assertFalse(m.eye_now()[0]["hit"], "neither sees anything")
        b, go = brake.Brake(), {"B": ("s", 100), "C": ("s", 100)}
        res = b.apply(go, w.layout(mapping.TANK), m.eye_now()[0], brake.settings({}), R, 1.5)
        self.assertEqual(res, go)
        m.feed(tel({"S2": {"kind": "us", "value": 5}, "S4": {"kind": "ir", "value": 99}}), mapping.TANK, now=1.75)
        res = b.apply(go, w.layout(mapping.TANK), m.eye_now()[0], brake.settings({}), R, 1.75)
        self.assertEqual(res, {"B": ("s", 0), "C": ("s", 0)}, "the ultrasonic's obstacle stops the car though infrared is on a later port")


if __name__ == "__main__":
    unittest.main()
