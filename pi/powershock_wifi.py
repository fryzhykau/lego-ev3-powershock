#!/usr/bin/env python3
"""Keeps the Raspberry Pi on the strongest saved WiFi network, for a robot that drives from
room to room and floor to floor.

NetworkManager only changes network when the current one is lost altogether. On the robot,
that means clinging to a far router while a near one (or an extender) is in reach, with
choppy video until the link finally breaks. This checks the signal every few seconds. When
it's weak, and a saved network, or another access point of the same network, is clearly
stronger, it switches to that.

The rule (choose) is the same one the brick program uses (ev3/src/powershock/WifiRoam.java):
- a signal of -60 dBm or better is good enough: never look for better;
- below that, switch only to one at least 8 dB stronger;
- after a switch, stay at least a minute, so it never flaps between two.

Only networks already saved on the Pi are used: add them with `sudo nmtui`, or
`sudo nmcli --ask device wifi connect <name>`. This script never sees a password.

Runs as root (scanning and switching need it), as the service powershock-wifi: see
docs/CAMERA.md. Standard library only; uses nmcli.

    sudo python3 powershock_wifi.py            # keep switching (the service runs this)
    sudo python3 powershock_wifi.py --dry-run  # only say what it would do
"""
import argparse
import subprocess
import sys
import time

GOOD = -60      # dBm: at or above this, don't look for better
MARGIN = 8      # dB: a network must be this much stronger to switch to it
HOLD = 60.0     # s: after a switch, stay at least this long
CHECK = 5.0     # s between looks at the signal
RESCAN = 30.0   # s: scan for networks at most this often, and only while the signal is below GOOD
SAVED_EVERY = 60.0  # s: how often the list of saved networks is read again


def choose(current, seen, now, last_switch, good=GOOD, margin=MARGIN, hold=HOLD):
    """current: (ssid, bssid, dBm) of the access point in use, or None when not connected (then
    NetworkManager picks one itself). seen: [(ssid, bssid, dBm)] of saved networks in reach.
    Returns the one to switch to, or None to stay."""
    if current is None or now - last_switch < hold or current[2] >= good:
        return None
    others = [s for s in seen if s[1] != current[1]]
    if not others:
        return None
    best = max(others, key=lambda s: s[2])
    return best if best[2] >= current[2] + margin else None


def dbm(percent):
    """NetworkManager's signal (0..100) in dBm: it works it out as 2 x (dBm + 100)."""
    return percent / 2 - 100


def fields(line):
    """One line of `nmcli -t` output: fields split at ':', where '\\:' is a colon inside a field."""
    out, cur, i = [], "", 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur += line[i + 1]
            i += 2
            continue
        if c == ":":
            out.append(cur)
            cur = ""
        else:
            cur += c
        i += 1
    out.append(cur)
    return out


class NM:
    """The few nmcli calls needed. `run` is replaceable, for the tests."""

    def __init__(self, run=None):
        self.run = run or self._run

    @staticmethod
    def _run(args, timeout=30):
        p = subprocess.run(["nmcli"] + args, capture_output=True, text=True, timeout=timeout)
        return p.stdout if p.returncode == 0 else ""

    def saved(self):
        """{ssid: connection name} for the saved WiFi networks."""
        out = {}
        for line in self.run(["-t", "-f", "NAME,TYPE", "connection", "show"]).splitlines():
            f = fields(line)
            if len(f) >= 2 and f[1] == "802-11-wireless":
                ssid = self.run(["-g", "802-11-wireless.ssid", "connection", "show", "id", f[0]]).strip()
                if ssid:
                    out.setdefault(ssid, f[0])
        return out

    def aps(self, rescan=False):
        """(in use or None, [(ssid, bssid, dBm)] of everything in reach)."""
        raw = self.run(["-t", "-f", "IN-USE,SSID,BSSID,SIGNAL", "device", "wifi", "list", "--rescan",
                        "yes" if rescan else "no"], timeout=40)
        current, seen = None, []
        for line in raw.splitlines():
            f = fields(line)
            if len(f) < 4 or not f[1]:
                continue
            try:
                ap = (f[1], f[2].upper(), dbm(int(f[3])))
            except ValueError:
                continue
            seen.append(ap)
            if f[0].strip() == "*":
                current = ap
        return current, seen

    def switch(self, name, bssid):
        return self.run(["connection", "up", "id", name, "ap", bssid], timeout=60) != ""


def main(argv=None):
    ap = argparse.ArgumentParser(description="Keep the Pi on the strongest saved WiFi network.")
    ap.add_argument("--dry-run", action="store_true", help="only say what it would do")
    ap.add_argument("--once", action="store_true", help="look once, then stop")
    args = ap.parse_args(argv)
    nm = NM()
    saved, saved_at, last_switch, last_scan = {}, -1e9, -1e9, -1e9
    while True:
        now = time.monotonic()
        if now - saved_at >= SAVED_EVERY:
            saved, saved_at = nm.saved(), now
        current, seen = nm.aps()
        if current and current[2] < GOOD and now - last_scan >= RESCAN:
            current, seen = nm.aps(rescan=True)  # weak: look around for something better
            last_scan = now
        pick = choose(current, [s for s in seen if s[0] in saved], now, last_switch)
        if pick:
            print(f"{current[0]} is weak ({current[2]:.0f} dBm): switching to {pick[0]} ({pick[2]:.0f} dBm)", flush=True)
            if not args.dry_run:
                if not nm.switch(saved[pick[0]], pick[1]):
                    print("the switch didn't work; staying where it is", flush=True)
            last_switch = now
        elif args.once:
            print(f"staying on {current[0]} ({current[2]:.0f} dBm)" if current else "not connected", flush=True)
        if args.once:
            return 0
        time.sleep(CHECK)


if __name__ == "__main__":
    sys.exit(main())
