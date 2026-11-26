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


if __name__ == "__main__":
    unittest.main()
