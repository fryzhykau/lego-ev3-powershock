"""The console's link to the brick, against the built-in practice brick (no hardware)."""
import socket
import threading
import time
import unittest
from unittest.mock import patch

import ev3_console as c


GO = {"lx": 0, "ly": -1.0, "rx": 0, "ry": -1.0, "l2": 0, "r2": 0, "pad": False}


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
        self.link = c.Link(practice=True)

    def tearDown(self):
        self.link.disconnect()

    def test_connect_opens_exactly_one_connection(self):
        before = self.fake.clients
        self.assertTrue(self.link.connect("127.0.0.1"))
        time.sleep(2.0)  # the sender thread must not open a second one
        self.assertEqual(self.fake.clients - before, 1)

    def test_stop_is_not_undone_by_late_input(self):
        self.assertTrue(self.link.connect("127.0.0.1"))
        before = self.link.status()["epoch"]
        old = self.link.arm(before)["epoch"]
        self.assertTrue(self.link.set_input(GO, old))
        self.assertTrue(self.link.stop())
        self.assertFalse(self.link.arm(before)["ok"])  # a delayed arm request cannot undo Stop
        self.assertFalse(self.link.set_input(GO, self.link.status()["epoch"]))  # knowing the epoch does not arm
        self.assertFalse(self.link.set_input(GO, old))
        self.assertFalse(self.link.send_line("M A rotate 90 30", old))
        self.assertFalse(self.link.calibrate_steer(old)["ok"])
        self.assertFalse(self.link.turn("start", "left", old)["ok"])
        new = self.link.arm(self.link.status()["epoch"])["epoch"]
        self.assertTrue(self.link.set_input(GO, new))
        self.assertFalse(self.link.set_input({}, old))
        with self.link.lock:
            self.assertEqual(self.link.inp, GO)

    def test_stop_rejects_a_motor_line_waiting_for_the_socket(self):
        self.assertTrue(self.link.connect("127.0.0.1"))
        epoch = self.link.arm(self.link.status()["epoch"])["epoch"]
        self.assertTrue(self.link.set_input(GO, epoch))
        queued, cancelled = threading.Event(), threading.Event()
        send, disarm = self.link._send, self.link._disarm
        result = []

        def observe_send(s, gen, line):
            if line.startswith("M A"):
                queued.set()
            return send(s, gen, line)

        def observe_disarm():
            disarm()
            cancelled.set()

        with patch.object(self.link, "_send", observe_send), patch.object(self.link, "_disarm", observe_disarm):
            with self.link.send_lock:
                test = threading.Thread(target=lambda: result.append(self.link.send_line("M A rotate 90 30", epoch)))
                test.start()
                self.assertTrue(queued.wait(1))
                stop = threading.Thread(target=self.link.stop)
                stop.start()
                self.assertTrue(cancelled.wait(1))
            test.join(1)
            stop.join(1)
        self.assertEqual(result, [False])
        self.assertFalse(stop.is_alive())

    def test_input_timeout_stops_an_active_motor_test_and_disarms(self):
        self.assertTrue(self.link.connect("127.0.0.1"))
        epoch = self.link.arm(self.link.status()["epoch"])["epoch"]
        self.assertTrue(self.link.send_line("M A rotate 3600 20", epoch))

        def speed():
            t = self.link.status()["telemetry"] or {}
            return t.get("motors", {}).get("A", {}).get("speed", 0)

        deadline = time.monotonic() + 2
        while not speed() and time.monotonic() < deadline:
            self.assertTrue(self.link.set_input({}, epoch))
            time.sleep(0.02)
        self.assertNotEqual(speed(), 0)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if not speed() and not self.link.status()["armed"]:
                break
            time.sleep(0.02)
        else:
            self.fail("Motor test did not move and then stop when the input expired")
        self.assertFalse(self.link.set_input(GO, epoch))

    def test_stop_cancels_steering_calibration_before_a_late_worker_can_move(self):
        self.assertTrue(self.link.connect("127.0.0.1"))
        self.link.set_mapping(c.mapping.validate(c.mapping.CAR))
        epoch = self.link.arm(self.link.status()["epoch"])["epoch"]
        started, finish = threading.Event(), threading.Event()
        sent = []
        find = self.link.cal.find_steer

        def calibrate(port, send, tacho):
            started.set()
            finish.wait(1)
            sent.append(send(f"M {port} rotate 90 30"))
            return find(port, send, tacho)

        with patch.object(self.link.cal, "find_steer", calibrate):
            self.assertTrue(self.link.calibrate_steer(epoch)["ok"])
            self.assertTrue(started.wait(1))
            self.link.stop()
            new_epoch = self.link.arm(self.link.status()["epoch"])["epoch"]
            self.assertTrue(self.link.set_input({}, new_epoch))
            finish.set()
            deadline = time.monotonic() + 1
            while self.link.cal_port and time.monotonic() < deadline:
                time.sleep(0.01)
        self.assertEqual(sent, [False])
        result = self.link.cal.snapshot()
        self.assertEqual(result["job"]["state"], "stopped")
        self.assertIsNone(result["steer"])

    def test_motors_on_does_not_survive_a_dropped_link(self):
        go = {"lx": 0, "ly": 0, "rx": 0, "ry": -1.0, "l2": 0, "r2": 0, "stop": False}
        self.assertFalse(self.link.set_input(go, epoch=self.link.epoch))  # no link: nothing to switch on
        self.assertTrue(self.link.connect("127.0.0.1"))
        armed_on = self.link.arm(self.link.status()["epoch"])["epoch"]
        self.assertTrue(self.link.set_input(go, epoch=armed_on))
        self.link.disconnect()  # the link drops ...
        self.assertTrue(self.link.connect("127.0.0.1"))  # ... and comes straight back
        with self.link.lock:
            self.assertIsNone(self.link.inp)  # nothing left over to drive with
        self.assertFalse(self.link.set_input(go, epoch=armed_on))  # the page must switch Motors on again
        with self.link.lock:
            self.assertIsNone(self.link.inp)
        self.assertTrue(self.link.set_input(go, epoch=self.link.arm(self.link.status()["epoch"])["epoch"]))

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
