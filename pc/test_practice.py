"""Exercise the same Practice profile and settings routes as the console page."""
import http.client
import json
import threading
import unittest
from unittest.mock import patch

import ev3_console as c


class PracticeProfileTest(unittest.TestCase):
    def setUp(self):
        self.real = c.Link()
        self.practice = c.Link(practice=True)
        self.real.set_mapping(c.mapping.validate(dict(c.mapping.CAR, name="brick")))
        self.real.world.config = self.real.cal.config = None
        self.real.world.set_robot({"wheel": 71})
        self.real.cal.turn_result("left", 120, 45, 14)
        self.real.cal.data["speed"]["samples"] = [(8.0, 40.0)]
        real, fake = self.real, c.FakeEV3()
        globals_ = patch.multiple(c, link=real, practice_link=self.practice, fake=fake)
        globals_.start()
        self.addCleanup(globals_.stop)
        self.addCleanup(real.disconnect)
        self.addCleanup(c.set_practice, False)
        srv = c.ThreadingHTTPServer(("127.0.0.1", 0), c.Handler)
        self.addCleanup(srv.server_close)
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.port = srv.server_port
        port = patch.object(c, "HTTP_PORT", self.port)
        port.start()
        self.addCleanup(port.stop)

    def request(self, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            conn.request("GET" if body is None else "POST", "/api/" + path,
                         body=None if body is None else json.dumps(body),
                         headers={"X-PowerShock": "1", "Content-Type": "application/json"})
            with conn.getresponse() as res:
                self.assertEqual(res.status, 200)
                return json.load(res)
        finally:
            conn.close()

    def test_settings_and_delayed_writes_stay_in_their_own_profile(self):
        before = {path: self.request(path) for path in ("mapping", "map", "calibration")}
        with patch.object(c.mapping, "save") as saved:
            self.assertTrue(self.request("fake", {"on": True})["ok"])
            self.assertTrue(self.request("status")["link"]["connected"])
            self.assertTrue(self.request("mapping")["practice"])
            self.assertEqual(self.request("mapping")["mapping"], c.mapping.default())
            self.assertEqual(self.request("map")["robot"], c.worldmap.ROBOT)
            self.assertEqual(self.request("calibration")["speed"]["samples"], 0)
            practice_mapping = dict(c.mapping.CAR, name="practice", brake={"required": True})
            self.assertTrue(self.request("mapping", {"practice": True, "mapping": practice_mapping})["ok"])
            self.assertTrue(self.request("map/robot", {"practice": True, "robot": {"wheel": 83}})["ok"])
            self.practice.cal.turn_result("right", 140, 45, 14)
            self.assertTrue(self.request("calibration/forget", {"practice": True, "what": "turn"})["ok"])
            self.assertFalse(self.request("mapping", {"practice": False, "mapping": practice_mapping})["ok"])
            self.assertTrue(self.request("fake", {"on": False})["ok"])
            self.assertFalse(self.request("map/robot", {"practice": True, "robot": {"wheel": 99}})["ok"])
            self.assertEqual(self.request("mapping"), before["mapping"])
            self.assertEqual(self.request("map")["robot"], before["map"]["robot"])
            self.assertEqual(self.request("calibration"), before["calibration"])
            saved.assert_not_called()
            self.assertTrue(self.request("fake", {"on": True})["ok"])
            self.assertEqual(self.request("mapping")["mapping"]["name"], "practice")
            self.assertEqual(self.request("map")["robot"]["wheel"], 83)

    def test_copy_controls_is_explicit_and_leaves_geometry_and_calibration_alone(self):
        self.assertFalse(self.request("fake/copy-controls", {})["ok"])
        self.assertTrue(self.request("fake", {"on": True})["ok"])
        practice = self.request("mapping")["mapping"]
        with patch.object(c.mapping, "save") as saved:
            self.assertTrue(self.request("fake/copy-controls", {})["ok"])
            saved.assert_called_once_with(practice)
        self.assertTrue(self.request("fake", {"on": False})["ok"])
        self.assertEqual(self.request("mapping")["mapping"], practice)
        self.assertEqual(self.request("map")["robot"]["wheel"], 71)
        self.assertEqual(self.request("calibration")["speed"]["samples"], 1)
