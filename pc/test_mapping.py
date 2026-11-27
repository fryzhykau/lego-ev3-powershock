import unittest

import mapping as mp

STILL = {"lx": 0, "ly": 0, "rx": 0, "ry": 0, "l2": 0, "r2": 0}


def inp(**kw):
    d = dict(STILL)
    d.update(kw)
    return d


class TankTest(unittest.TestCase):
    def setUp(self):
        self.m = mp.Mapper(mp.validate(mp.TANK))

    def test_still(self):
        r = self.m.step(inp(), 0.02)
        self.assertEqual((r["B"], r["C"], r["A"], r["D"]), (("s", 0), ("s", 0), ("s", 0), None))

    def test_forward_half_speed_without_r2(self):
        r = self.m.step(inp(ly=-1), 0.02)
        self.assertEqual((r["B"], r["C"]), (("s", 50), ("s", 50)))

    def test_spin_right_full_with_r2(self):
        r = self.m.step(inp(lx=1, r2=1), 0.02)
        self.assertEqual((r["B"], r["C"]), (("s", 100), ("s", -100)))

    def test_line(self):
        r = self.m.step(inp(ly=-1, r2=1, ry=-1), 0.02)
        self.assertEqual(mp.line(r), "P A=s:100 B=s:100 C=s:100 D=-")


class CarTest(unittest.TestCase):
    def setUp(self):
        self.m = mp.Mapper(mp.validate(mp.CAR))

    def test_throttle_ramps_up_gradually(self):
        # smoothing 0.8 s from 0 to 100%: after 0.4 s at full stick (+R2) it is about half way
        vals = [self.m.step(inp(ry=-1, r2=1), 0.02)["B"][1] for _ in range(20)]
        self.assertEqual(vals[0], 2)
        self.assertEqual(vals[-1], 50)

    def test_steering_goes_to_an_angle_and_holds_on_stop(self):
        for _ in range(50):
            r = self.m.step(inp(lx=1), 0.02)
        self.assertEqual(r["D"], ("p", 45, 60))
        r = self.m.step(inp(lx=1), 0.02, stop=True)
        self.assertEqual(r["D"], ("p", 45, 60))  # stop holds the wheels where they are
        self.assertEqual(r["B"], ("s", 0))       # but the drive stops at once

    def test_stop_is_immediate_for_speed(self):
        for _ in range(30):
            self.m.step(inp(ry=-1), 0.02)
        self.assertEqual(self.m.step(None, 0.02)["B"], ("s", 0))

    def test_reverse(self):
        for _ in range(60):
            r = self.m.step(inp(ry=1), 0.02)
        self.assertEqual(r["B"], ("s", -60))


class HandbrakeTest(unittest.TestCase):
    """Circle: the drive motors brake while it's held, steering stays live, and the power comes back on release."""

    def test_drive_brakes_and_steering_stays(self):
        m = mp.Mapper(mp.validate(mp.CAR))
        for _ in range(50):
            m.step(inp(ry=-1, r2=1, lx=1), 0.02)
        r = m.step(inp(ry=-1, r2=1, lx=-1, hand=True), 0.02)
        self.assertEqual((r["B"], r["C"]), (("s", 0), ("s", 0)))
        for _ in range(50):
            r = m.step(inp(ry=-1, r2=1, lx=-1, hand=True), 0.02)
        self.assertEqual(r["D"], ("p", -45, 60), "you can still steer, to catch the slide")
        self.assertEqual(r["B"], ("s", 0))
        r = m.step(inp(ry=-1, r2=1, lx=-1), 0.02)
        self.assertEqual(r["B"], ("s", 100), "the throttle kept ramping underneath")

    def test_followers_brake_too(self):
        m = mp.Mapper(grouped(invert=True))
        for _ in range(60):
            m.step(inp(ry=-1), 0.02)
        r = m.step(inp(ry=-1, hand=True), 0.02)
        self.assertEqual((r["A"], r["B"]), (("s", 0), ("s", 0)))

    def test_tank_just_stops(self):
        r = mp.Mapper(mp.validate(mp.TANK)).step(inp(ly=-1, r2=1, ry=-1, hand=True), 0.02)
        self.assertEqual(mp.line(r), "P A=s:0 B=s:0 C=s:0 D=-")

    def test_stop_still_wins_after_letting_go(self):
        m = mp.Mapper(mp.validate(mp.CAR))
        for _ in range(50):
            m.step(inp(ry=-1, r2=1, hand=True), 0.02)
        m.step(inp(ry=-1, r2=1, hand=True), 0.02, stop=True)
        r = m.step(inp(ry=-1, r2=1), 0.02)
        self.assertEqual(r["B"], ("s", 2), "after a stop, power ramps up from nothing again")


def grouped(invert=False):
    """Two large motors on one axle (A leads, B follows) and steering on D."""
    m = dict(mp.CAR, ports={
        "A": {"mode": "speed", "input": "RY", "invert": False, "max": 100, "smooth": 0.8},
        "B": {"mode": "follow", "leader": "A", "invert": invert},
        "C": {"mode": "off"},
        "D": mp.CAR["ports"]["D"],
    })
    return mp.validate(m)


class GroupTest(unittest.TestCase):
    def test_follower_gets_exactly_what_its_leader_gets(self):
        m = mp.Mapper(grouped())
        for _ in range(20):
            r = m.step(inp(ry=-1, r2=1), 0.02)  # smoothing on the leader: the follower ramps with it
            self.assertEqual(r["B"], r["A"])
        self.assertEqual(r["A"], ("s", 50))
        self.assertEqual(m.step(None, 0.02)["B"], ("s", 0))  # and stops with it

    def test_reversed_follower(self):
        m = mp.Mapper(grouped(invert=True))
        for _ in range(60):
            r = m.step(inp(ry=-1), 0.02)
        self.assertEqual((r["A"], r["B"]), (("s", 60), ("s", -60)))

    def test_follower_of_steering(self):
        m = dict(mp.CAR, ports=dict(mp.CAR["ports"], A={"mode": "follow", "leader": "D", "invert": True}))
        mm = mp.Mapper(mp.validate(m))
        for _ in range(50):
            r = mm.step(inp(lx=1), 0.02)
        self.assertEqual((r["D"], r["A"]), (("p", 45, 60), ("p", -45, 60)))

    def test_bad_leaders_turn_the_port_off(self):
        ports = {"A": {"mode": "follow", "leader": "B"}, "B": {"mode": "follow", "leader": "A"},
                 "C": {"mode": "follow", "leader": "C"}, "D": {"mode": "follow", "leader": "Z"}}
        out = mp.validate(dict(mp.CAR, ports=ports))
        self.assertEqual({p: c["mode"] for p, c in out["ports"].items()}, dict.fromkeys("ABCD", "off"))
        out = mp.validate(dict(mp.CAR, ports=dict(mp.CAR["ports"], A={"mode": "follow", "leader": "B"},
                                                  B={"mode": "off"})))
        self.assertEqual(out["ports"]["A"], {"mode": "off"})  # a leader that does nothing

    def test_saved_in_port_order(self):
        self.assertEqual(list(grouped()["ports"]), ["A", "B", "C", "D"])

    def test_tests_move_the_whole_group(self):
        m = grouped(invert=True)
        self.assertEqual(mp.test_lines(m, "A", "run", 40, 50), ["M A run 40 50", "M B run -40 50"])
        # pressing the follower's button moves the leader too, the right way round
        self.assertEqual(mp.test_lines(m, "B", "rotate", 90, 50), ["M A rotate -90 50", "M B rotate 90 50"])
        self.assertEqual(mp.test_lines(m, "B", "stop", 0, 50), ["M A stop 0 50", "M B stop 0 50"])
        self.assertEqual(mp.test_lines(m, "D", "run", 40, 50), ["M D run 40 50"])  # not grouped

    def test_the_drive_layout_sees_both(self):
        import worldmap
        lay = worldmap.layout(grouped(invert=True))
        self.assertEqual(lay["type"], "car")
        self.assertEqual(lay["drive"], {"A": 1, "B": -1})
        self.assertEqual(lay["steer"], ("D", 1))


class ValidateTest(unittest.TestCase):
    def test_rejects_unknown_input(self):
        bad = mp.validate(mp.CAR)
        bad["ports"]["B"]["input"] = "XX"
        with self.assertRaises(ValueError):
            mp.validate(bad)

    def test_clamps_numbers(self):
        m = mp.validate({"ports": {"B": {"mode": "speed", "input": "RY", "max": 500, "smooth": -1}}})
        self.assertEqual(m["ports"]["B"]["max"], 100)
        self.assertEqual(m["ports"]["B"]["smooth"], 0)


class SetMappingTest(unittest.TestCase):
    def test_slider_change_keeps_steering_where_it_is(self):
        mpr = mp.Mapper(mp.validate(mp.CAR))
        for _ in range(50):
            mpr.step({"lx": 1.0}, 0.02)
        before = mpr.value["D"]
        changed = mp.validate(dict(mp.CAR, sticks={"deadzone": 12}))
        mpr.set_mapping(changed)
        self.assertEqual(mpr.value["D"], before)

    def test_mode_change_resets_that_port(self):
        mpr = mp.Mapper(mp.validate(mp.CAR))
        for _ in range(50):
            mpr.step({"lx": 1.0}, 0.02)
        m = mp.validate(mp.CAR)
        m["ports"]["D"] = {"mode": "speed", "input": "RY", "invert": False, "max": 100, "smooth": 0}
        mpr.set_mapping(m)
        self.assertEqual(mpr.value["D"], 0.0)

    def test_off_port_sends_dash(self):
        line = mp.line(mp.Mapper(mp.validate(mp.CAR)).step({"ry": -1.0}, 0.02))
        self.assertIn("A=-", line)


class SticksTest(unittest.TestCase):
    def cal(self, **kw):
        s = mp._sticks({})
        s.update(kw)
        return s

    def test_defaults_match_old_dead_zone(self):
        self.assertEqual(mp.stick("lx", 0.05), 0.0)
        self.assertAlmostEqual(mp.stick("lx", 1.0), 1.0)
        self.assertAlmostEqual(mp.stick("lx", 0.54), 0.5, places=2)

    def test_offset_makes_rest_zero(self):
        s = self.cal(deadzone=0, offset={"lx": 0.1, "ly": 0, "rx": 0, "ry": 0})
        self.assertEqual(mp.stick("lx", 0.1, s), 0.0)
        self.assertAlmostEqual(mp.stick("lx", 1.0, s), 1.0)
        self.assertAlmostEqual(mp.stick("lx", -1.0, s), -1.0)

    def test_span_makes_short_stick_reach_full(self):
        s = self.cal(deadzone=0, span={"lx": [-1.0, 0.9], "ly": [-1, 1], "rx": [-1, 1], "ry": [-1, 1]})
        self.assertAlmostEqual(mp.stick("lx", 0.9, s), 1.0)
        self.assertAlmostEqual(mp.stick("lx", 0.45, s), 0.5)

    def test_keyboard_skips_offset(self):
        s = self.cal(deadzone=0, offset={"lx": 0.2, "ly": 0, "rx": 0, "ry": 0})
        self.assertEqual(mp.stick("lx", 1.0, s, pad=False), 1.0)

    def test_curve_is_gentler_near_centre_but_keeps_ends(self):
        s = self.cal(deadzone=0, curve=100)
        self.assertAlmostEqual(mp.stick("lx", 0.5, s), 0.125)
        self.assertAlmostEqual(mp.stick("lx", 1.0, s), 1.0)
        self.assertAlmostEqual(mp.stick("lx", -0.5, s), -0.125)

    def test_validate_keeps_and_clamps_sticks(self):
        m = mp.validate({"ports": {}, "sticks": {"deadzone": 99, "curve": 50, "offset": {"lx": 0.9}}})
        self.assertEqual(m["sticks"]["deadzone"], 40)
        self.assertEqual(m["sticks"]["offset"]["lx"], 0.3)
        self.assertEqual(m["sticks"]["curve"], 50)


STEER = {"mode": "position", "invert": False, "smooth": 0.3, "input": "LX", "range": 45, "speed": 60}
THROTTLE = {"mode": "speed", "invert": False, "smooth": 0.8, "input": "RY", "max": 100}


def car(**ports):
    m = mp.validate({"name": "custom", "ports": {p: c for p, c in ports.items()}})
    return m


class FitTest(unittest.TestCase):
    """Moving the controls onto the motors that are plugged in."""

    def test_car_rewired(self):
        # set up for large motors on A + B and steering on D, but plugged in as large A + C, medium B
        m = car(A=THROTTLE, B={"mode": "follow", "leader": "A", "invert": True}, D=STEER)
        f = mp.fit(m, {"A": "large", "B": "medium", "C": "large"})
        self.assertEqual(f["ports"]["B"]["mode"], "position")
        self.assertEqual(f["ports"]["B"]["range"], 45)  # the steering keeps its settings
        self.assertEqual(f["ports"]["A"], m["ports"]["A"])
        self.assertEqual(f["ports"]["C"], {"mode": "follow", "leader": "A", "invert": True})
        self.assertEqual(f["ports"]["D"], {"mode": "off"})
        self.assertEqual(mp.describe(f), "A drives, with C reversed; B steers")

    def test_a_mapping_that_works_is_left_alone(self):
        m = car(A=THROTTLE, C={"mode": "follow", "leader": "A", "invert": True}, B=STEER)
        self.assertIsNone(mp.fit(m, {"A": "large", "B": "medium", "C": "large"}))
        self.assertIsNone(mp.fit(m, {"A": "large", "B": "large", "C": "large", "D": "medium"}))  # a spare is fine

    def test_waits_while_a_motor_is_missing(self):
        # a loose cable: moving the leader onto its mirrored partner would turn the car's direction round
        m = car(A=THROTTLE, C={"mode": "follow", "leader": "A", "invert": True}, B=STEER)
        self.assertIsNone(mp.fit(m, {"B": "medium", "C": "large"}))
        self.assertIsNone(mp.fit(m, {}))

    def test_tank_sides_move_in_order(self):
        m = mp.validate(mp.TANK)  # A on the right stick, B left wheel, C right wheel
        f = mp.fit(m, {"A": "large", "B": "large", "D": "large"})
        self.assertEqual(f["ports"]["A"]["mode"], "speed")
        self.assertEqual(f["ports"]["B"]["side"], "left")
        self.assertEqual(f["ports"]["D"]["side"], "right")
        self.assertEqual(f["ports"]["C"], {"mode": "off"})

    def test_steering_takes_a_large_motor_when_there_is_no_medium(self):
        m = car(A=THROTTLE, D=STEER)
        f = mp.fit(m, {"B": "large", "C": "large"})
        self.assertEqual(f["ports"]["B"]["mode"], "speed")  # driving takes the first large motor
        self.assertEqual(f["ports"]["C"]["mode"], "position")  # and steering what's left


if __name__ == "__main__":
    unittest.main()
