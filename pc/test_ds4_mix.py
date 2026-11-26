import unittest

from ds4_mix import mix


class MixTest(unittest.TestCase):
    def test_centered_is_still(self):
        self.assertEqual(mix(0.0, 0.0, 0.0, 0.0), (0, 0, 0))

    def test_deadzone_ignores_drift(self):
        self.assertEqual(mix(0.05, -0.07, 0.06, 0.0), (0, 0, 0))

    def test_full_forward_half_speed_without_turbo(self):
        self.assertEqual(mix(0.0, -1.0, 0.0, 0.0), (50, 50, 0))

    def test_full_forward_full_speed_with_turbo(self):
        self.assertEqual(mix(0.0, -1.0, 0.0, 1.0), (100, 100, 0))

    def test_back(self):
        self.assertEqual(mix(0.0, 1.0, 0.0, 1.0), (-100, -100, 0))

    def test_spin_right(self):
        self.assertEqual(mix(1.0, 0.0, 0.0, 1.0), (100, -100, 0))

    def test_forward_plus_turn_is_normalized(self):
        left, right, _ = mix(1.0, -1.0, 0.0, 1.0)
        self.assertEqual((left, right), (100, 0))

    def test_aux_up_is_positive(self):
        self.assertEqual(mix(0.0, 0.0, -1.0, 1.0), (0, 0, 100))

    def test_cross_stops_everything(self):
        self.assertEqual(mix(1.0, -1.0, -1.0, 1.0, stop=True), (0, 0, 0))

    def test_out_of_range_input_is_clamped(self):
        self.assertEqual(mix(0.0, -1.5, 0.0, 2.0), (100, 100, 0))


if __name__ == "__main__":
    unittest.main()
