"""Devices in the wrong kind of port: a motor in a sensor port, a sensor in a motor port."""
import unittest
from unittest import mock

import ev3_brick
import ev3_console

# What a brick reported with its three motors plugged into sensor ports 1, 3 and 4
MOTORS_IN_SENSOR_PORTS = "T 6.9 0.234 0.000 A=126:126 B=126:126 C=126:126 D=126:126 1=127:127 2=126:126 3=127:127 4=127:127"
RIGHT = "T 7.9 0.2 0.0 A=125:7 B=125:7 C=126:126 D=125:8 1=126:126 2=126:126 3=122:32 4=122:33"


def ports(line):
    return ev3_brick.parse_telemetry(line)["ports"]


class PortCheckTest(unittest.TestCase):
    def setUp(self):
        self.c = ev3_brick.PortCheck()

    def test_motors_in_sensor_ports(self):
        self.assertEqual(self.c.update(ports(MOTORS_IN_SENSOR_PORTS), 0.0), {})  # might be sensors starting up
        wrong = self.c.update(ports(MOTORS_IN_SENSOR_PORTS), ev3_brick.WRONG_AFTER_S)
        self.assertEqual(sorted(wrong), ["S1", "S3", "S4"])
        self.assertIn("A, B, C or D", wrong["S1"])

    def test_everything_in_its_place(self):
        for t in (0.0, 10.0):
            self.assertEqual(self.c.update(ports(RIGHT), t), {})

    def test_sensor_in_a_motor_port(self):
        line = "T 7.9 0.2 0.0 A=122:33 B=127:127 C=126:126 D=125:8 1=126:126 2=126:126 3=126:126 4=126:126"
        self.c.update(ports(line), 0.0)
        wrong = self.c.update(ports(line), 5.0)
        self.assertEqual(sorted(wrong), ["A", "B"])
        self.assertIn("1, 2, 3 or 4", wrong["A"])

    def test_moving_the_cable_clears_it_and_the_wait_starts_again(self):
        self.c.update(ports(MOTORS_IN_SENSOR_PORTS), 0.0)
        self.assertTrue(self.c.update(ports(MOTORS_IN_SENSOR_PORTS), 5.0))
        self.assertEqual(self.c.update(ports(RIGHT), 6.0), {})
        self.assertEqual(self.c.update(ports(MOTORS_IN_SENSOR_PORTS), 7.0), {})  # plugged in wrong again: wait again

    def test_ports_powershock_holds_are_left_alone(self):
        line = "T 7.9 0.2 0.0 A=0:0h B=125:7h C=126:126 D=126:126 1=126:126 2=126:126 3=127:127h 4=0:0h"
        self.c.update(ports(line), 0.0)
        self.assertEqual(self.c.update(ports(line), 10.0), {})


class BrickGoneTest(unittest.TestCase):
    """A brick that stops answering: its last port check isn't shown as if it were current."""

    def test_ports_forgotten_when_the_brick_stops_answering(self):
        b = ev3_console.BrickInfo()
        b.host, b.ports, b.ports_at = "<brick address>", {"A": {"label": "Large motor"}}, 1.0
        with mock.patch.object(ev3_brick, "details", side_effect=ev3_brick.BrickError("can't log in")):
            b._refresh("<brick address>")
        r = b.get("<brick address>", max_age=1e9)
        self.assertFalse(r["details"]["ok"])
        self.assertIsNone(r["ports"])
        self.assertIsNone(r["portsAt"])

    def test_ports_kept_while_it_answers(self):
        b = ev3_console.BrickInfo()
        b.host, b.ports, b.ports_at = "<brick address>", {"A": {"label": "Large motor"}}, 1e12  # checked just now
        with mock.patch.object(ev3_brick, "details", return_value={"ok": True, "receiverListening": False}):
            b._refresh("<brick address>")
        self.assertEqual(b.get("<brick address>", max_age=1e9)["ports"], {"A": {"label": "Large motor"}})


if __name__ == "__main__":
    unittest.main()
