"""The obstacle brake on the laptop: it slows and stops for what's in front, and only ever takes speed away."""
import time
import unittest

import brake as b
import ev3_console as c
import mapping
import vision
import worldmap as w

TANK = w.layout(mapping.TANK)          # B left, C right
CAR = w.layout(mapping.CAR)            # B and C drive, D steers
ROBOT = dict(w.ROBOT)
ON = b.settings({})
NOW = 100.0


def eye(dist, hit=True, age=0.0, speed=0.0):
    return {"dist": dist, "hit": hit, "kind": "ir", "at": NOW - age, "speed": speed}


def tank(left, right, a="-"):
    return {"A": None, "B": ("s", left), "C": ("s", right), "D": None}


class SettingsTest(unittest.TestCase):
    def test_defaults_are_on(self):
        self.assertEqual(b.settings(None), {"on": True, "stop": b.STOP, "slow": b.SLOW, "camera": True, "required": False})

    def test_kept_in_range_and_slow_beyond_stop(self):
        s = b.settings({"on": False, "stop": 999, "slow": 1})
        self.assertFalse(s["on"])
        self.assertEqual(s["stop"], 40.0)
        self.assertEqual(s["slow"], 45.0)

    def test_nonsense_falls_back(self):
        self.assertEqual(b.settings({"stop": "x", "slow": None}), ON)

    def test_saved_with_the_mapping(self):
        expected = {"on": True, "stop": 20.0, "slow": 50.0, "camera": False, "required": True}
        self.assertEqual(mapping.validate(dict(mapping.TANK, brake=expected))["brake"], expected)
        self.assertFalse(b.settings({"required": "true"})["required"])
        self.assertEqual(mapping.validate(mapping.TANK)["brake"], ON)  # older saved mappings get the default


class FacingTest(unittest.TestCase):
    def test_directions(self):
        self.assertEqual(b.facing(0), 1)
        self.assertEqual(b.facing(-20), 1)
        self.assertEqual(b.facing(180), -1)
        self.assertEqual(b.facing(-170), -1)
        self.assertEqual(b.facing(90), 0)

    def test_factor(self):
        self.assertEqual(b.factor(10, 15, 40), 0.0)
        self.assertEqual(b.factor(15, 15, 40), 0.0)
        self.assertAlmostEqual(b.factor(27.5, 15, 40), 0.5)
        self.assertEqual(b.factor(60, 15, 40), 1.0)
        self.assertEqual(b.factor(17, 15, 40), 0.0)  # almost there: stop rather than crawl


class BrakeTest(unittest.TestCase):
    def setUp(self):
        self.k = b.Brake()

    def run_(self, res, e, lay=TANK, conf=ON, robot=ROBOT, now=NOW):
        return self.k.apply(res, lay, e, conf, robot, now)

    def test_clear_road_is_untouched(self):
        self.assertEqual(self.run_(tank(80, 80), eye(70, hit=False)), tank(80, 80))
        self.assertEqual(self.k.state["state"], "clear")

    def test_stops_forward_close_to_something(self):
        self.assertEqual(self.run_(tank(80, 80), eye(10)), tank(0, 0))
        self.assertEqual(self.k.state["state"], "stop")
        self.assertTrue(self.k.state["braking"])

    def test_slows_in_between(self):
        out = self.run_(tank(80, 80), eye(27.5))
        self.assertEqual(out, tank(40, 40))
        self.assertEqual(self.k.state["state"], "slow")

    def test_can_back_away_when_stopped(self):
        self.assertEqual(self.run_(tank(-60, -60), eye(5)), tank(-60, -60))
        self.assertFalse(self.k.state["braking"])

    def test_can_turn_on_the_spot_when_stopped(self):
        self.assertEqual(self.run_(tank(-50, 50), eye(5)), tank(-50, 50))

    def test_turning_part_kept_while_forward_part_is_cut(self):
        # forward 50 + turn 30: the forward part goes, the turn stays
        self.assertEqual(self.run_(tank(20, 80), eye(5)), tank(-30, 30))

    def test_reversed_motor(self):
        m = mapping.validate(dict(mapping.TANK, ports=dict(mapping.TANK["ports"], B=dict(mapping.TANK["ports"]["B"], invert=True))))
        lay = w.layout(m)
        self.assertEqual(self.run_(tank(-80, 80), eye(5), lay=lay), tank(0, 0))  # B runs backwards to go forwards
        self.k = b.Brake()
        self.assertEqual(self.run_(tank(80, -80), eye(5), lay=lay), tank(80, -80))  # this is reversing

    def test_other_ports_left_alone(self):
        res = dict(tank(80, 80), A=("s", 70))
        self.assertEqual(self.run_(res, eye(5))["A"], ("s", 70))

    def test_car_scales_the_drive_but_not_the_steering(self):
        res = {"A": None, "B": ("s", 60), "C": ("s", 60), "D": ("p", 30, 60)}
        out = self.run_(res, eye(5), lay=CAR)
        self.assertEqual(out, {"A": None, "B": ("s", 0), "C": ("s", 0), "D": ("p", 30, 60)})
        self.k = b.Brake()
        res = {"A": None, "B": ("s", -60), "C": ("s", -60), "D": ("p", 30, 60)}
        self.assertEqual(self.run_(res, eye(5), lay=CAR), res)

    def test_allows_for_driving_since_the_reading(self):
        # 30 cm away when read 0.2 s ago, driving at 40 cm/s: now about 16 cm away
        out = self.run_(tank(80, 80), eye(30, age=0.2, speed=40))
        self.assertLess(out["B"][1], 10)
        self.assertGreater(self.k.state["dist"], 15)
        self.assertLess(self.k.state["dist"], 17)

    def test_old_reading_means_stop(self):
        self.assertEqual(self.run_(tank(80, 80), eye(70, hit=False, age=2.0)), tank(0, 0))
        self.assertEqual(self.k.state["state"], "blind")

    def test_no_sensor_no_brake(self):
        self.assertEqual(self.run_(tank(80, 80), None), tank(80, 80))
        self.assertEqual(self.k.state["state"], "no sensor")

    def test_sideways_sensor_no_brake(self):
        self.assertEqual(self.run_(tank(80, 80), eye(5), robot=dict(ROBOT, eyeAngle=90)), tank(80, 80))
        self.assertEqual(self.k.state["state"], "sideways")

    def test_sensor_facing_back_brakes_reversing(self):
        back = dict(ROBOT, eyeAngle=180)
        self.assertEqual(self.run_(tank(80, 80), eye(5), robot=back), tank(80, 80))
        self.assertEqual(self.run_(tank(-80, -80), eye(5), robot=back, now=NOW + 0.02), tank(0, 0))

    def test_turned_off(self):
        self.assertEqual(self.run_(tank(80, 80), eye(5), conf=b.settings({"on": False})), tank(80, 80))
        self.assertEqual(self.k.state["state"], "off")

    def test_speed_comes_back_gradually(self):
        self.run_(tank(100, 100), eye(5))
        out = self.run_(tank(100, 100), eye(70, hit=False, age=0), now=NOW + 0.1)  # a clear reading 0.1 s later
        self.assertEqual(out, tank(20, 20))
        out = self.run_(tank(100, 100), eye(70, hit=False, age=0), now=NOW + 0.2)
        self.assertEqual(out, tank(40, 40))

    def test_once_stopped_waits_for_a_clear_margin(self):
        self.run_(tank(100, 100), eye(10))
        self.assertEqual(self.run_(tank(100, 100), eye(18.5), now=NOW + 0.1), tank(0, 0))  # just past the crawl limit
        self.assertNotEqual(self.run_(tank(100, 100), eye(21), now=NOW + 0.2), tank(0, 0))

    def test_never_adds_speed(self):
        for dist in (0, 10, 20, 30, 50, 80):
            for l, r in ((100, 100), (30, 90), (-40, 60), (0, 0), (-100, -100)):
                k = b.Brake()
                out = k.apply(tank(l, r), TANK, eye(dist), ON, ROBOT, NOW)
                self.assertLessEqual(abs(out["B"][1]), max(abs(l), abs(r)))
                self.assertLessEqual(abs(out["C"][1]), max(abs(l), abs(r)))


class DecisionTest(unittest.TestCase):
    """What the brake decided, for the map's instrument panel."""

    def setUp(self):
        self.k = b.Brake()

    def step(self, res, e, now, cam=None):
        return self.k.apply(res, TANK, e, ON, ROBOT, now, cam)

    def test_asked_and_given(self):
        self.step(tank(80, 80), eye(27.5), NOW)
        self.assertEqual((self.k.state["asked"], self.k.state["given"]), (80, 40))
        self.step(tank(-60, -60), eye(5), NOW + 0.02)  # backing away isn't braked
        self.assertEqual((self.k.state["asked"], self.k.state["given"]), (-60, -60))
        self.k.apply(tank(50, 50), TANK, None, ON, ROBOT, NOW + 0.04)
        self.assertEqual(self.k.state["asked"], 50)

    def test_nothing_logged_while_clear(self):
        for n in range(10):
            self.step(tank(80, 80), eye(70, hit=False), NOW + n * 0.02)
        self.assertEqual(self.k.decisions(NOW), [])

    def test_stop_is_logged_at_once_and_slowing_once_it_holds(self):
        t = NOW
        self.step(tank(80, 80), eye(30), t)
        self.assertEqual(self.k.decisions(t), [])  # slowing, but not for long enough yet
        for n in range(1, 20):
            self.step(tank(80, 80), eye(30), t + n * 0.02)
        self.step(tank(80, 80), eye(5), t + 0.5)
        d = self.k.decisions(t + 1.0)
        self.assertEqual([e["what"] for e in d], ["stop", "slow"])  # newest first
        self.assertEqual(d[0]["dist"], 5.0)
        self.assertAlmostEqual(d[0]["ago"], 0.5)

    def test_only_what_changes_the_driving_counts(self):
        # something close ahead, but the robot isn't driving at it: nothing decided
        for n in range(30):
            self.step(tank(0, 0), eye(10), NOW + n * 0.02)
        self.assertEqual(self.k.decisions(NOW + 1), [])

    def test_flicker_at_the_edge_isnt_logged(self):
        for n in range(30):
            self.step(tank(80, 80), eye(39.5 if n % 2 else 41), NOW + n * 0.02)
        self.assertEqual(self.k.decisions(NOW + 1), [])

    def test_keeps_the_latest(self):
        t = NOW
        for n in range(30):
            for _ in range(2):
                self.step(tank(80, 80), eye(5 if n % 2 else 70, hit=n % 2 == 1, age=NOW - t), t)  # a fresh reading
                t += 0.5
        self.assertEqual(len(self.k.decisions(t)), b.LOG_KEEP)


def view(dist, age=0.0, good=True, careful=None, speed=0.0):
    """What the camera sees in the robot's way (worldmap.WorldMap.camera_now)."""
    return {"dist": dist, "at": NOW - age, "good": good, "careful": careful, "speed": speed}


class CameraTest(unittest.TestCase):
    def setUp(self):
        self.k = b.Brake()

    def run_(self, res, e, cam, conf=ON, robot=ROBOT, now=NOW):
        return self.k.apply(res, TANK, e, conf, robot, now, cam)

    def test_camera_alone_brakes(self):
        self.assertEqual(self.run_(tank(80, 80), None, view(10)), tank(0, 0))
        self.assertEqual((self.k.state["state"], self.k.state["src"]), ("stop", "camera"))

    def test_nearer_of_the_two_counts(self):
        # the infrared sensor sees 60 cm along its line; the camera sees something at 20 cm to one side
        self.run_(tank(80, 80), eye(60), view(20))
        self.assertEqual(self.k.state["src"], "camera")
        self.assertAlmostEqual(self.k.state["dist"], 20 + (ROBOT["camAhead"] - ROBOT["eyeAhead"]) / 10)
        self.k = b.Brake()
        self.run_(tank(80, 80), eye(20), view(60))
        self.assertEqual(self.k.state["src"], "infrared")

    def test_camera_nothing_in_the_way(self):
        self.assertEqual(self.run_(tank(80, 80), None, view(None)), tank(80, 80))
        self.assertEqual(self.k.state["state"], "clear")

    def test_camera_that_stopped_means_stop(self):
        self.assertEqual(self.run_(tank(80, 80), None, view(None, age=2.0)), tank(0, 0))
        self.assertEqual(self.k.state["state"], "blind")

    def test_stopped_camera_doesnt_matter_with_infrared(self):
        self.assertEqual(self.run_(tank(80, 80), eye(70, hit=False), view(10, age=2.0)), tank(80, 80))

    def test_patterned_floor_is_ignored(self):
        self.assertEqual(self.run_(tank(80, 80), None, view(10, good=False)), tank(80, 80))

    def test_camera_can_be_left_out(self):
        off = dict(ON, camera=False)
        self.assertEqual(self.run_(tank(80, 80), None, view(10), conf=off), tank(80, 80))
        self.assertEqual(self.k.state["state"], "no sensor")

    def test_camera_doesnt_brake_reversing(self):
        back = dict(ROBOT, eyeAngle=180)
        self.assertEqual(self.run_(tank(80, 80), eye(70, hit=False), view(5), robot=back), tank(80, 80))

    def test_more_room_for_people_and_pets(self):
        # 45 cm ahead is clear road normally
        self.assertEqual(self.run_(tank(80, 80), eye(70, hit=False), view(45)), tank(80, 80))
        self.k = b.Brake()
        out = self.run_(tank(80, 80), eye(70, hit=False), view(45, careful="dog"))
        self.assertLess(out["B"][1], 40)
        self.assertEqual(self.k.state["careful"], "dog")
        self.assertEqual(self.k.state["stop"], 30.0)
        self.k = b.Brake()
        out = self.run_(tank(80, 80), eye(70, hit=False), view(None, careful="person"))
        self.assertEqual(out, tank(40, 40))  # nothing in the way, but half speed at most


class RequiredCoverageTest(unittest.TestCase):
    def setUp(self):
        self.brake = b.Brake()
        self.conf = dict(ON, required=True)

    def step(self, power=60, sensor=None, cam=None, angle=0, layout=TANK, now=NOW):
        return self.brake.apply(tank(power, power), layout, sensor, self.conf, dict(ROBOT, eyeAngle=angle), now, cam)

    def test_forward_needs_a_fresh_usable_reading(self):
        for cam in (None, view(80, good=False), view(80, age=2)):
            with self.subTest(cam=cam):
                self.assertEqual(self.step(sensor=eye(70, hit=False, age=2), cam=cam), tank(0, 0))
                self.assertEqual(self.brake.state["blindReason"], "ahead")
        self.assertEqual(self.step(cam=view(None), now=NOW + 0.2), tank(24, 24))  # gradual recovery
        self.assertEqual(self.brake.state["blindReason"], None)

    def test_camera_can_cover_forward_with_the_range_sensor_facing_back(self):
        self.assertEqual(self.step(sensor=eye(5), cam=view(None), angle=180), tank(60, 60))
        self.assertEqual(self.step(power=-60, sensor=eye(5), cam=view(None), angle=180), tank(0, 0))
        self.assertEqual(self.brake.state["state"], "stop")

    def test_reverse_needs_a_fresh_rear_reading(self):
        self.assertEqual(self.step(power=-60, sensor=eye(70, hit=False), cam=view(None)), tank(0, 0))
        self.assertEqual(self.brake.state["blindReason"], "behind")
        self.assertEqual(self.step(power=-60, sensor=eye(70, hit=False), angle=180, now=NOW + 0.2), tank(-24, -24))

    def test_tank_can_turn_on_the_spot_without_a_reading(self):
        res = tank(60, -60)
        self.assertEqual(self.brake.apply(res, TANK, None, self.conf, ROBOT, NOW), res)

    def test_missing_layout_blocks_speed_commands(self):
        self.assertEqual(self.step(layout=None), tank(0, 0))
        self.assertEqual(self.brake.state["blindReason"], "layout")

    def test_switches_can_disable_coverage_or_the_camera(self):
        self.conf["camera"] = False
        self.assertEqual(self.step(cam=view(None)), tank(0, 0))
        self.conf["on"] = False
        self.assertEqual(self.step(), tank(60, 60))


class PracticeRoomTest(unittest.TestCase):
    """End to end: the practice robot drives full speed at the box ahead of it and stops short."""

    @classmethod
    def setUpClass(cls):
        cls.fake = c.FakeEV3()
        err = cls.fake.start()
        if err:
            raise unittest.SkipTest(err)

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()

    def drive(self, link, ly, seconds):
        status = link.status()
        epoch = status["epoch"] if status["armed"] else link.arm(status["epoch"])["epoch"]
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.assertTrue(link.set_input({"lx": 0.0, "ly": ly, "rx": 0.0, "ry": 0.0, "l2": 0.0,
                                            "r2": 1.0, "pad": False}, epoch))
            time.sleep(0.05)

    def test_stops_before_the_box(self):
        link = c.Link()
        try:
            link.set_mapping(mapping.validate(mapping.TANK))  # not the user's saved controls
            link.world.robot = dict(w.ROBOT)                  # nor their saved robot size
            self.assertTrue(link.connect("127.0.0.1"))
            time.sleep(0.6)
            link.world.reset()
            self.drive(link, -1.0, 3.5)  # stick pushed up, full boost
            snap = link.world.snapshot()
            gap = link.world.eye_now()[0]["dist"]  # what the infrared sensor reads once it has stopped
            self.assertGreater(snap["pose"]["x"], 25, "it should have driven most of the way")
            self.assertGreater(gap, 12, f"stopped {gap:.1f} cm from the box")
            self.assertLess(gap, 22, f"stopped {gap:.1f} cm from the box")
            st = link.status()["brake"]
            self.assertEqual(st["state"], "stop")
            self.assertTrue(st["braking"])
            x = snap["pose"]["x"]
            self.drive(link, 1.0, 0.8)  # and it can back away
            self.assertLess(link.world.snapshot()["pose"]["x"], x - 5)
        finally:
            link.disconnect()

    def test_camera_alone_stops_before_the_box(self):
        """The infrared sensor turned sideways, so only the practice camera sees the box ahead."""
        link = c.Link()
        see = vision.Vision(None, model="nowhere.onnx", practice=self.fake.picture,
                            on_floor=lambda s: link.world.surround(s) if s else link.world.end_view())
        try:
            link.set_mapping(mapping.validate(mapping.TANK))
            link.world.robot = dict(w.ROBOT, eyeAngle=90)
            self.assertTrue(link.connect("127.0.0.1"))
            time.sleep(0.6)
            link.world.reset()
            end = time.monotonic() + 1.0
            while time.monotonic() < end:  # the camera starts watching
                see.watch_floor()
                time.sleep(0.05)
            epoch = link.arm(link.status()["epoch"])["epoch"]
            end = time.monotonic() + 3.5
            while time.monotonic() < end:
                see.watch_floor()
                self.assertTrue(link.set_input({"lx": 0.0, "ly": -1.0, "rx": 0.0, "ry": 0.0, "l2": 0.0,
                                                "r2": 1.0, "pad": False}, epoch))
                time.sleep(0.05)
            x = link.world.snapshot()["pose"]["x"]
            st = link.status()["brake"]
            self.assertEqual((st["state"], st["src"]), ("stop", "camera"))
            # the box's near side is at x = 70, and the robot's front about 6 cm ahead of its axle
            self.assertGreater(x, 25, "it should have driven most of the way")
            self.assertLess(x, 70 - 6 - 8, f"stopped at x = {x:.1f}, too close to the box")
        finally:
            with see.lock:
                see.floor_until = 0.0
            link.disconnect()


if __name__ == "__main__":
    unittest.main()
