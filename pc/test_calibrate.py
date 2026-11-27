"""Car calibration (pc/calibrate.py): steering limits, turning circle, top speed against the battery."""
import math
import os
import tempfile
import time
import unittest

import calibrate as cb
import ev3_console as c
import mapping
import worldmap as w


def fresh():
    return cb.Calibration(os.path.join(tempfile.mkdtemp(), "calibration.json"))


class SteeringMotor:
    """A pretend steering motor with end stops at lo..hi (in its own count), driven by test lines."""

    def __init__(self, lo=-40.0, hi=70.0):
        self.angle, self.lo, self.hi, self.lines = 0.0, lo, hi, []

    def send(self, line):
        self.lines.append(line)
        _, _, action, value, _ = line.split()
        v = int(value)
        if action == "run":
            self.angle = max(self.lo, min(self.hi, self.angle + v * 0.5))
        elif action == "rotate":
            self.angle = max(self.lo, min(self.hi, self.angle + v))
        elif action == "zero":
            self.lo, self.hi, self.angle = self.lo - self.angle, self.hi - self.angle, 0.0
        return True

    def tacho(self):
        return round(self.angle)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class SteerTest(unittest.TestCase):
    def test_finds_both_stops_and_centres(self):
        cal, motor, clock = fresh(), SteeringMotor(), Clock()
        r = cal.find_steer("D", motor.send, motor.tacho, sleep=clock.sleep, clock=clock)
        self.assertAlmostEqual(r["eachWay"], 55, delta=2)
        self.assertEqual(r["range"], int(r["eachWay"] - cb.MARGIN))
        self.assertEqual((motor.lo, motor.hi), (-55.0, 55.0))  # centre is now 0
        self.assertIn("M D zero 0 50", motor.lines)
        self.assertTrue(all(abs(int(x.split()[3])) <= cb.STEER_SPEED for x in motor.lines if " run " in x))  # gently
        self.assertEqual(fresh().snapshot()["steer"], None)
        self.assertEqual(cb.Calibration(cal.config).snapshot()["steer"]["eachWay"], r["eachWay"])  # saved

    def test_a_motor_that_doesnt_move(self):
        cal, motor, clock = fresh(), SteeringMotor(lo=-1, hi=1), Clock()
        with self.assertRaises(RuntimeError):
            cal.find_steer("D", motor.send, motor.tacho, sleep=clock.sleep, clock=clock)

    def test_no_reading(self):
        cal, clock = fresh(), Clock()
        with self.assertRaises(RuntimeError):
            cal.find_steer("D", lambda line: True, lambda: None, sleep=clock.sleep, clock=clock)


class TurnTest(unittest.TestCase):
    def test_circle_to_wheel_angle(self):
        cal = fresh()
        # rear axle on a circle 40 cm across, axle spacing 14 cm: wheels at atan(14 / 20) = 35 degrees
        r = cal.turn_result("left", 40 * math.pi, 45, 14)
        self.assertAlmostEqual(r["across"], 40, delta=0.1)
        self.assertAlmostEqual(r["wheel"], 35.0, delta=0.1)
        self.assertAlmostEqual(r["ratio"], 35.0 / 45, delta=0.001)
        cal.turn_result("right", 44 * math.pi, 45, 14)
        self.assertAlmostEqual(cal.steer_ratio(), (r["ratio"] + math.degrees(math.atan(14 / 22)) / 45) / 2, delta=0.002)

    def test_too_short(self):
        with self.assertRaises(RuntimeError):
            fresh().turn_result("left", 10, 45, 14)


class TopSpeedTest(unittest.TestCase):
    def test_learns_from_full_power_straight_driving(self):
        cal, t = fresh(), 0.0
        for volts, speed in ((8.0, 40.0), (7.0, 35.0)):
            for _ in range(200):  # 4 s at 50 a second
                cal.observe(100, True, speed, volts, t)
                t += 0.02
            cal.observe(0, True, 0, volts, t)  # let go
            t += 0.02
        snap = cal.snapshot(volts=7.5)
        self.assertGreater(snap["speed"]["samples"], 6)
        self.assertAlmostEqual(snap["speed"]["perVolt"], 5.0, delta=0.05)
        self.assertAlmostEqual(snap["speed"]["now"], 37.5, delta=0.5)

    def test_ignores_turning_part_power_and_the_first_second(self):
        cal, t = fresh(), 0.0
        for straight, power in ((False, 100), (True, 60)):
            for _ in range(200):
                cal.observe(power, straight, 30.0, 8.0, t)
                t += 0.02
        for _ in range(40):  # 0.8 s: still getting up to speed
            cal.observe(100, True, 30.0, 8.0, t)
            t += 0.02
        self.assertEqual(cal.snapshot()["speed"]["samples"], 0)

    def test_forget(self):
        cal = fresh()
        cal.data["speed"]["samples"] = [(8.0, 40.0)]
        self.assertTrue(cal.forget("speed"))
        self.assertEqual(cal.snapshot()["speed"]["samples"], 0)
        self.assertFalse(cal.forget("everything"))


class PracticeCarTest(unittest.TestCase):
    """Both calibrations on the practice car: steering motor D stops at 55 degrees each way, and
    starts 12 degrees off centre."""

    @classmethod
    def setUpClass(cls):
        cls.fake = c.FakeEV3()
        err = cls.fake.start()
        if err:
            raise unittest.SkipTest(err)

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()

    def wait(self, cond, limit, keep=None):
        t = time.monotonic()
        while time.monotonic() - t < limit:
            if keep:
                keep()
            if cond():
                return True
            time.sleep(0.05)
        return False

    def test_steering_then_turning_circle(self):
        link = c.Link()
        link.cal = fresh()
        cfg = os.path.join(tempfile.mkdtemp(), "worldmap.json")
        link.world = w.WorldMap(cfg)  # not the owner's saved robot size
        real_save = mapping.save
        mapping.save = lambda m: None  # not the owner's saved controls
        try:
            link.set_mapping(mapping.validate(mapping.CAR))
            self.assertTrue(link.connect("127.0.0.1"))
            self.assertTrue(self.wait(lambda: link.tacho("D") is not None, 3))
            self.assertTrue(link.calibrate_steer()["ok"])
            self.assertTrue(self.wait(lambda: (link.cal.snapshot()["job"] or {}).get("state") in ("done", "failed"), 30))
            snap = link.cal.snapshot()
            self.assertEqual(snap["job"]["state"], "done", snap["job"])
            self.assertAlmostEqual(snap["steer"]["eachWay"], c.PRACTICE_STOP, delta=4)
            self.assertEqual(link.mapper.mapping["ports"]["D"]["range"], snap["steer"]["range"])

            # the turning circle needs Motors on: the page sends input all the while
            still = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0, "l2": 0.0, "r2": 0.0, "stop": False, "pad": False}
            self.assertFalse(link.turn("start", "left")["ok"])  # Motors off
            link.set_input(still)
            self.assertTrue(link.turn("start", "left")["ok"])
            th0 = self.fake.pose[2]

            def keep():
                link.set_input(still)
                link.turn("keep")
            self.assertTrue(self.wait(lambda: abs(self.fake.pose[2] - th0) >= 2 * math.pi, 30, keep), "drove a full circle")
            r = link.turn("done")
            self.assertTrue(r["ok"], r)
            # the practice car: wheels at full lock (the steering range), axle spacing 14 cm
            lock = snap["steer"]["range"]
            self.assertAlmostEqual(r["result"]["wheel"], lock, delta=4)
            self.assertAlmostEqual(link.world.robot["steerRatio"], 1.0, delta=0.1)
        finally:
            mapping.save = real_save
            link.disconnect()


if __name__ == "__main__":
    unittest.main()
