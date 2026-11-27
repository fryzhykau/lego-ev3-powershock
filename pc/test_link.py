"""The console's link to the brick, against the built-in practice brick (no hardware)."""
import socket
import time
import unittest

import ev3_console as c


class LinkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = c.FakeEV3()
        err = cls.fake.start()
        if err:
            raise unittest.SkipTest(err)

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()

    def setUp(self):
        self.link = c.Link()

    def tearDown(self):
        self.link.disconnect()

    def test_connect_opens_exactly_one_connection(self):
        before = self.fake.clients
        self.assertTrue(self.link.connect("127.0.0.1"))
        time.sleep(2.0)  # the sender thread must not open a second one
        self.assertEqual(self.fake.clients - before, 1)

    def test_stop_is_not_undone_by_late_input(self):
        self.link.connect("127.0.0.1")
        self.link.set_input({"lx": 1.0, "ly": 0, "rx": 0, "ry": -1.0, "l2": 0, "r2": 0, "stop": False})
        self.link.stop_input()
        self.link.set_input({"lx": 1.0, "ly": 0, "rx": 0, "ry": -1.0, "l2": 0, "r2": 0, "stop": False})  # arrives late
        with self.link.lock:
            self.assertIsNone(self.link.inp)

    def test_silent_brick_is_dropped(self):
        # a server that accepts but never sends status lines
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        old = c.EV3_PORT
        c.EV3_PORT = port
        try:
            self.assertTrue(self.link.connect("127.0.0.1"))
            conn, _ = srv.accept()
            srv.close()  # no reconnecting to it afterwards
            dropped = False
            for _ in range(30):
                time.sleep(0.1)
                with self.link.lock:
                    if self.link.sock is None:
                        dropped = True
                        break
            self.assertTrue(dropped, "a brick that never answers should be dropped within ~2 s")
            conn.close()
        finally:
            c.EV3_PORT = old
            srv.close()


class FitTest(unittest.TestCase):
    """The controls move onto the motors that are plugged in, but never under someone driving."""

    REWIRED = "T 7.9 0.2 0.0 A=125:7 B=125:8 C=125:7 D=126:126 1=126:126 2=126:126 3=122:32 4=122:33"

    def setUp(self):
        self.link = c.Link()
        self.saved = []
        self.link.on_fit = self.saved.append
        steer = {"mode": "position", "input": "LX", "range": 45, "speed": 60}
        self.link.set_mapping(c.mapping.validate({"ports": {
            "A": {"mode": "speed", "input": "RY"}, "B": {"mode": "follow", "leader": "A", "invert": True}, "D": steer}}))
        self.t = c.ev3_brick.parse_telemetry(self.REWIRED)

    def ports(self):
        return {p: v["mode"] for p, v in self.link.mapper.mapping["ports"].items()}

    def test_waits_for_the_motors_to_settle_then_fits(self):
        self.link._fit(self.t, 100.0)
        self.link._fit(self.t, 101.0)
        self.assertEqual(self.ports()["D"], "position")  # cables may still be going in
        self.link._fit(self.t, 101.6)
        self.assertEqual(self.ports(), {"A": "speed", "B": "position", "C": "follow", "D": "off"})
        self.assertEqual(len(self.saved), 1)
        self.assertIn("B steers", self.link.status()["fitted"]["text"])

    def test_never_while_driving(self):
        self.link.inp, self.link.inp_at = {"ry": 1.0}, 101.0
        self.link._fit(self.t, 100.0)
        self.link._fit(self.t, 102.0)
        self.assertEqual(self.ports()["D"], "position")
        self.link._fit(self.t, 103.5)  # 2.5 s since the last input
        self.assertEqual(self.ports()["B"], "position")

    def test_a_link_of_its_own_saves_nothing(self):
        link = c.Link()  # tests and tools: only the console's own link writes mapping.json
        self.assertIsNone(link.on_fit)


if __name__ == "__main__":
    unittest.main()
