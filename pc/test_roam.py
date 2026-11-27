"""Moving between WiFi networks: the Pi's switcher (pi/powershock_wifi.py), the networks saved on
the brick (pc/ev3_brick.py), and the console finding the brick at a new address."""
import ipaddress
import os
import sys
import tempfile
import time
import unittest

import ev3_brick
import ev3_console as c

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pi"))
import powershock_cam as cam  # noqa: E402
import powershock_wifi as pw  # noqa: E402

A1 = ("HomeNetwork", "AA:BB:CC:DD:EE:FF", -72)
A2 = ("HomeNetwork", "00:00:00:00:00:00", -55)   # the same network's other access point
EXT = ("HomeNetwork_EXT", "FF:FF:FF:FF:FF:FF", -50)


class ChooseTest(unittest.TestCase):
    def test_strong_enough_stays(self):
        self.assertIsNone(pw.choose(("HomeNetwork", A1[1], -58), [EXT], 100, -1e9))

    def test_weak_moves_to_clearly_stronger(self):
        self.assertEqual(pw.choose(A1, [A1, A2, EXT], 100, -1e9), EXT)

    def test_not_for_a_little_better(self):
        self.assertIsNone(pw.choose(A1, [A1, ("HomeNetwork_EXT", "FF:FF:FF:FF:FF:FF", -67)], 100, -1e9))

    def test_another_access_point_of_the_same_network(self):
        self.assertEqual(pw.choose(A1, [A1, A2], 100, -1e9), A2)

    def test_waits_after_a_switch(self):
        self.assertIsNone(pw.choose(A1, [EXT], 100, 100 - pw.HOLD + 1))
        self.assertEqual(pw.choose(A1, [EXT], 100, 100 - pw.HOLD - 1), EXT)

    def test_not_connected_is_left_to_network_manager(self):
        self.assertIsNone(pw.choose(None, [EXT], 100, -1e9))


class NmcliTest(unittest.TestCase):
    def fake(self, args, timeout=30):
        self.calls.append(args)
        if args[:4] == ["-t", "-f", "NAME,TYPE", "connection"]:
            return "netplan-wlan0-Home:802-11-wireless\nlo:loopback\nExt:802-11-wireless\nOld:802-11-wireless\n"
        if args[:2] == ["-g", "802-11-wireless.ssid"]:
            return {"netplan-wlan0-Home": "HomeNetwork\n", "Ext": "HomeNetwork_EXT\n", "Old": "\n"}[args[-1]]
        if "wifi" in args and "list" in args:
            mac = lambda m: m.replace(":", "\\:")  # noqa: E731
            return (f"*:HomeNetwork:{mac(A1[1])}:56\n"
                    f" :HomeNetwork_EXT:{mac(EXT[1])}:100\n"
                    f" ::{mac(A2[1])}:90\n"           # a hidden network: no name
                    f" :Neighbours:{mac(A2[1])}:80\n")
        return "ok\n"

    def setUp(self):
        self.calls = []
        self.nm = pw.NM(run=self.fake)

    def test_fields_with_escaped_colons(self):
        self.assertEqual(pw.fields("*:Home\\:Net:AA\\:BB:56"), ["*", "Home:Net", "AA:BB", "56"])

    def test_saved_networks(self):
        self.assertEqual(self.nm.saved(), {"HomeNetwork": "netplan-wlan0-Home", "HomeNetwork_EXT": "Ext"})

    def test_access_points(self):
        current, seen = self.nm.aps()
        self.assertEqual(current, ("HomeNetwork", "AA:BB:CC:DD:EE:FF", -72.0))
        self.assertEqual(len(seen), 3)
        self.assertIn(("HomeNetwork_EXT", "FF:FF:FF:FF:FF:FF", -50.0), seen)
        self.assertIn("no", self.calls[-1])  # no scan unless asked
        self.nm.aps(rescan=True)
        self.assertIn("yes", self.calls[-1])

    def test_switch_asks_for_that_access_point(self):
        self.nm.switch("Ext", "FF:FF:FF:FF:FF:FF")
        self.assertEqual(self.calls[-1], ["connection", "up", "id", "Ext", "ap", "FF:FF:FF:FF:FF:FF"])

    def test_signal_in_dbm(self):
        self.assertEqual(pw.dbm(100), -50)
        self.assertEqual(pw.dbm(56), -72)


class PiSignalTest(unittest.TestCase):
    def write(self, text):
        p = os.path.join(tempfile.mkdtemp(), "wireless")
        with open(p, "w") as f:
            f.write(text)
        return p

    def test_reads_the_level(self):
        head = "Inter-| sta-|   Quality        |   Discarded packets\n face | tus | link level noise |  nwid  crypt\n"
        self.assertEqual(cam.wifi_signal(self.write(head + " wlan0: 0000   54.  -56.  -256        0      0\n")), -56)
        self.assertEqual(cam.wifi_signal(self.write(head + " wlan0: 0000   54.  200.  0        0      0\n")), -56)
        self.assertIsNone(cam.wifi_signal(self.write(head)))
        self.assertIsNone(cam.wifi_signal("/nowhere"))


CONF = ('ctrl_interface=/var/run/wpa_supplicant\n\nnetwork={\n\tssid="HomeNetwork"\n\tkey_mgmt=WPA-PSK\n\tpsk=' + "a" * 64 +
        '\n}\n\nnetwork={\n\tssid=' + b"HomeNetwork_EXT".hex() + '\n\tkey_mgmt=NONE\n}\n')


class BrickNetworksTest(unittest.TestCase):
    def test_reads_the_blocks(self):
        nets = ev3_brick.conf_networks(CONF)
        self.assertEqual([s for s, _ in nets], [b"HomeNetwork", b"HomeNetwork_EXT"])

    def test_adding_keeps_the_others_and_replaces_its_own(self):
        out = ev3_brick.conf_with(CONF, b"HomeNetwork", "network={\n\tssid=00\n\tkey_mgmt=NONE\n}")
        self.assertEqual(len(ev3_brick.conf_networks(out)), 2)
        self.assertNotIn('"HomeNetwork"', out)
        self.assertIn(b"HomeNetwork_EXT".hex(), out)
        self.assertTrue(out.startswith("ctrl_interface="))

    def test_forgetting(self):
        out = ev3_brick.conf_with(CONF, b"HomeNetwork_EXT", None)
        self.assertEqual([s for s, _ in ev3_brick.conf_networks(out)], [b"HomeNetwork"])

    def test_join_adds_without_the_password(self):
        sent = []

        def ssh(host, command, stdin=None, timeout=30):
            sent.append((command, stdin))
            if command.startswith("cat /home"):
                return CONF
            return "192.168.1.40 COMPLETED"
        real, ev3_brick.ssh = ev3_brick.ssh, ssh
        try:
            r = ev3_brick.wifi_join("<brick address>", "Upstairs", "password1")
        finally:
            ev3_brick.ssh = real
        self.assertEqual(r, {"ok": True, "ip": "192.168.1.40"})
        conf = sent[-1][1].decode()
        self.assertEqual([s for s, _ in ev3_brick.conf_networks(conf)], [b"HomeNetwork", b"HomeNetwork_EXT", b"Upstairs"])
        self.assertNotIn("password1", conf)
        self.assertNotIn("password1", " ".join(cmd for cmd, _ in sent))

    def test_join_over_wifi_answers_before_wifi_restarts(self):
        sent = []

        def ssh(host, command, stdin=None, timeout=30):
            sent.append((command, stdin))
            return CONF if command.startswith("cat /home") else ""
        real, ev3_brick.ssh = ev3_brick.ssh, ssh
        try:
            r = ev3_brick.wifi_join("<brick address>", "Upstairs", "password1", over_wifi=True)
        finally:
            ev3_brick.ssh = real
        self.assertEqual(r, {"ok": True, "pending": True})
        self.assertIn("nohup", sent[-1][0])  # WiFi restarts after the answer has gone back
        self.assertEqual(len(ev3_brick.conf_networks(sent[-1][1].decode())), 3)
        self.assertNotIn("password1", sent[-1][1].decode())

    def test_saved_names_only(self):
        real = ev3_brick.ssh
        ev3_brick.ssh = lambda host, command, stdin=None, timeout=30: '"HomeNetwork"\n' + b"Caf\xc3\xa9".hex() + "\n"
        try:
            self.assertEqual(ev3_brick.wifi_saved("<brick address>"), ["HomeNetwork", "Café"])
        finally:
            ev3_brick.ssh = real

    def test_signal_in_the_status_line(self):
        t = ev3_brick.parse_telemetry("T 8.0 0.1 0.0 A=0:0 B=0:0 C=0:0 D=0:0 1=0:0 2=0:0 3=0:0 4=0:0 s4=ir:37 w=-62")
        self.assertEqual(t["wifi"], -62)


class FindTest(unittest.TestCase):
    """After the link drops, the console finds the brick again at a new address."""

    @classmethod
    def setUpClass(cls):
        cls.fake = c.FakeEV3()
        err = cls.fake.start()
        if err:
            raise unittest.SkipTest(err)

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()

    def test_which_addresses_can_change(self):
        self.assertTrue(c.moves("192.168.1.40"))
        self.assertFalse(c.moves(c.LEJOS_PAN_IP))  # Bluetooth
        self.assertFalse(c.moves("127.0.0.1"))      # Practice
        self.assertFalse(c.moves("ev3.local"))      # a name follows the brick by itself

    def test_finds_the_brick_program(self):
        self.assertTrue(c.is_receiver("127.0.0.1"))
        self.assertEqual(c.find_receivers([ipaddress.ip_network("127.0.0.1/32")]), ["127.0.0.1"])

    def test_link_follows_the_brick(self):
        link = c.Link()
        real = c.local_subnets
        c.local_subnets = lambda: [ipaddress.ip_network("127.0.0.1/32")]
        try:
            with link.lock:
                link.host, link.want = "192.168.1.40", True  # where it was; nothing answers there now
            link._find()
            t = time.monotonic()
            while not link.status()["connected"] and time.monotonic() - t < 5:
                time.sleep(0.05)
            st = link.status()
            self.assertTrue(st["connected"])
            self.assertEqual(st["host"], "127.0.0.1")
            self.assertEqual(st["moved"], {"from": "192.168.1.40", "to": "127.0.0.1"})
        finally:
            c.local_subnets = real
            link.disconnect()


if __name__ == "__main__":
    unittest.main()
