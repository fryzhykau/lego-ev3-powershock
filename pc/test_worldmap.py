"""The live map: where the robot is (odometry), what it saw (grid), and the practice room."""
import math
import os
import tempfile
import time
import unittest

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
        r = self.m.set_robot({"wheel": 5000, "track": "x", "gyroSign": -3, "evil": 1})
        self.assertEqual(r["wheel"], 200)
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


if __name__ == "__main__":
    unittest.main()
