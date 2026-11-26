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


if __name__ == "__main__":
    unittest.main()
