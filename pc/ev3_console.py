"""PowerShock Console: a local web app for finding, connecting to and driving the EV3.

    python pc\\ev3_console.py            then open http://127.0.0.1:8765

Python standard library only. The browser reads the DualShock 4 through the
Gamepad API, so pygame isn't needed here. The server keeps one TCP connection
to DS4Receiver on the brick (port 5000) and streams per-port commands ("P ...") at 50 Hz.
"""

import concurrent.futures
import ipaddress
import json
import math
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import camera  # noqa: E402
import vision  # noqa: E402
import ds4_hid  # noqa: E402
import ev3_brick  # noqa: E402
import mapping  # noqa: E402
import version  # noqa: E402
import worldmap  # noqa: E402
import brake  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UI_FILE = os.path.join(HERE, "console", "index.html")
CAM_FILE = os.path.join(HERE, "console", "camera.html")
HTTP_PORT = int(os.environ.get("POWERSHOCK_PORT", "8765"))
EV3_PORT = 5000
RATE_HZ = 50
INPUT_STALE_S = 0.3  # no command from the page for this long -> send zeros
LEJOS_PAN_IP = "10.0.1.1"
PORT_CHECK_EVERY_S = 60


def clamp100(v):
    return max(-100, min(100, int(v)))


class Link:
    """The TCP connection to the brick plus the 50 Hz sender thread."""

    def __init__(self):
        self.lock = threading.Lock()
        self.sock = None
        self.host = None
        self.want = False  # user asked to be connected; reconnect if dropped
        self.error = None
        self.connected_at = None
        self.connect_ms = None
        self.local_ip = None
        self.send_lock = threading.Lock()  # driving lines and test lines must not interleave
        self.open_lock = threading.Lock()  # one connection attempt at a time
        self.hold_until = 0.0  # after Stop, ignore input for a moment (a late request can't restart driving)
        self.telemetry = None  # live battery + ports streamed back by the receiver
        self.telemetry_at = 0.0
        self.brick_version = None  # from the receiver's "V <version>" line; None for versions before 0.7.0
        self.world = worldmap.WorldMap()  # live map from motor angles and sensor readings
        # Controls mapping: the page sends raw controller input; the mapping turns it into
        # per-port commands here, 50 times a second, with smoothing.
        self.mapper = mapping.Mapper(mapping.load())
        self.brake = brake.Brake()  # slows and stops for obstacles, after the mapping
        self.inp = None
        self.inp_at = 0.0
        self.out = {}
        self.sent = 0
        self.rate = 0.0
        threading.Thread(target=self._run, daemon=True).start()

    def set_input(self, inp):
        with self.lock:
            if inp is not None and time.monotonic() < self.hold_until:
                return
            self.inp, self.inp_at = inp, time.monotonic()

    def stop_input(self):
        with self.lock:
            self.inp, self.hold_until = None, time.monotonic() + 0.6

    def set_mapping(self, m):
        with self.lock:
            self.mapper.set_mapping(m)

    def connect(self, host):
        self.disconnect()
        with self.lock:
            self.host, self.want, self.error = host, True, None
        return self._open()

    def _open(self, blocking=True):
        if not self.open_lock.acquire(blocking):
            return False  # another attempt is under way
        try:
            return self._open_locked()
        finally:
            self.open_lock.release()

    def _open_locked(self):
        with self.lock:
            host, want, have = self.host, self.want, self.sock
        if have is not None or not want:
            return have is not None
        t0 = time.monotonic()
        try:
            s = socket.create_connection((host, EV3_PORT), timeout=3)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            # a small send buffer: if WiFi stalls, old commands don't pile up and arrive in a burst later
            s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 2048)
            s.settimeout(1)
        except OSError as e:
            with self.lock:
                self.error = f"{host}:{EV3_PORT} not reachable: {e.strerror or e}"
            return False
        with self.lock:
            if self.sock is not None or not self.want or self.host != host:
                s.close()  # someone else connected (or the user changed their mind) meanwhile
                return self.sock is not None
            self.sock = s
            self.brick_version = None
            self.world.relink()  # motor angles restart from 0 with a new connection
            self.telemetry_at = time.monotonic()  # grace period for the first status line
            self.connected_at = time.time()
            self.connect_ms = round((time.monotonic() - t0) * 1000, 1)
            self.local_ip = s.getsockname()[0]
            self.error = None
        threading.Thread(target=self._read, args=(s,), daemon=True).start()
        return True

    def _read(self, s):
        """Reads what the brick sends back: "V <version>" once, then "T <battery> <ports>" 4 per second."""
        buf = b""
        while True:
            with self.lock:
                if self.sock is not s:
                    return
            try:
                data = s.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if not data:
                return
            buf += data
            *lines, buf = buf.split(b"\n")
            for line in lines:
                text = line.decode("ascii", "replace")
                if text.startswith("V "):
                    v = text[2:].strip()[:32]
                    with self.lock:
                        if self.sock is s:
                            self.brick_version = v
                    continue
                t = ev3_brick.parse_telemetry(text)
                if t:
                    with self.lock:
                        self.telemetry, self.telemetry_at = t, time.monotonic()
                        m = self.mapper.mapping
                    self.world.feed(t, m)

    def disconnect(self):
        with self.lock:
            self.want = False
            s, self.sock = self.sock, None
        if s:
            try:
                s.sendall(b"0 0 0\n")
            except OSError:
                pass
            s.close()

    def send_line(self, line):
        """Sends one extra line (a motor test) on the driving connection."""
        with self.lock:
            s = self.sock
        if not s:
            return False
        try:
            with self.send_lock:
                s.sendall((line + "\n").encode("ascii"))
            return True
        except OSError:
            return False

    def status(self):
        with self.lock:
            return {
                "connected": self.sock is not None,
                "host": self.host,
                "want": self.want,
                "error": self.error,
                "connectMs": self.connect_ms,
                "localIp": self.local_ip if self.sock else None,
                "brickVersion": self.brick_version if self.sock else None,
                "telemetry": self.telemetry if self.sock and time.monotonic() - self.telemetry_at < 2.0 else None,
                # per port: ["s", pct] or ["p", deg, speed] or null
                "sending": {p: (list(v) if v else None) for p, v in self.out.items()},
                "mapping": self.mapper.mapping,
                "brake": dict(self.brake.state, on=self.mapper.mapping.get("brake", {}).get("on", True)),
                "rate": round(self.rate),
                "sent": self.sent,
            }

    def _run(self):
        period = 1.0 / RATE_HZ
        window_start, window_count = time.monotonic(), 0
        last_retry = 0.0
        last_t = time.monotonic()
        while True:
            t0 = time.monotonic()
            dt, last_t = t0 - last_t, t0
            eye, robot = self.world.eye_now()  # its own lock, taken before ours
            with self.lock:
                s, want = self.sock, self.want
                inp = self.inp if t0 - self.inp_at < INPUT_STALE_S else None
                m = self.mapper.mapping
                res = self.mapper.step(inp, dt, stop=bool(inp and inp.get("stop")))
                res = self.brake.apply(res, worldmap.layout(m), eye, m.get("brake") or brake.settings({}), robot, t0)
                self.out = res
            payload = mapping.line(res)
            if s:
                try:
                    with self.send_lock:
                        s.sendall((payload + "\n").encode("ascii"))
                    window_count += 1
                    with self.lock:
                        self.sent += 1
                except OSError as e:
                    with self.lock:
                        if self.sock is s:
                            self.sock = None
                            self.error = f"connection lost: {e.strerror or e}"
                    s.close()
            elif want and t0 - last_retry > 1.5:
                last_retry = t0
                self._open(blocking=False)
            # The brick sends status 4 times a second. Silence means the link is dead even if
            # Windows still accepts our writes: drop it hard (discarding queued commands) and retry.
            if s:
                with self.lock:
                    silent = self.sock is s and t0 - self.telemetry_at > 1.5
                    if silent:
                        self.sock = None
                        self.error = "the brick stopped answering"
                if silent:
                    _abort(s)
            if t0 - window_start >= 1.0:
                with self.lock:
                    self.rate = window_count / (t0 - window_start)
                window_start, window_count = t0, 0
            time.sleep(max(0.0, period - (time.monotonic() - t0)))


def _abort(s):
    """Closes a socket at once, throwing away anything still queued to send (TCP reset)."""
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("HH" if sys.platform == "win32" else "ii", 1, 0))
    except OSError:
        pass
    s.close()


def _box(x0, y0, x1, y1):
    return [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]


# The practice robot's room, in cm. It starts at (0, 0) facing +x, with a box just ahead.
PRACTICE_ROOM = _box(-60, -90, 220, 90) + _box(70, -10, 100, 30) + _box(140, -75, 175, -45)


def _range(x, y, th, segments, limit):
    """Distance from (x, y) along heading th to the nearest segment, or None beyond limit."""
    dx, dy = math.cos(th), math.sin(th)
    best = None
    for (ax, ay), (bx, by) in segments:
        ex, ey = bx - ax, by - ay
        den = dx * ey - dy * ex
        if abs(den) < 1e-9:
            continue
        t = ((ax - x) * ey - (ay - y) * ex) / den   # along the ray
        u = ((ax - x) * dy - (ay - y) * dx) / den   # along the segment
        if t >= 0 and 0 <= u <= 1 and (best is None or t < best):
            best = t
    return best if best is not None and best <= limit else None


def practice_sensors(x, y, th):
    """What the practice robot's IR sensor (proximity 0..100) and colour sensor (ID) read."""
    r = worldmap.ROBOT
    ex, ey = x + r["eyeAhead"] / 10 * math.cos(th), y + r["eyeAhead"] / 10 * math.sin(th)
    d = _range(ex, ey, th, PRACTICE_ROOM, worldmap.IR_RANGE)
    ir = 100 if d is None else max(0, min(99, round(d / worldmap.IR_RANGE * 100)))
    fx, fy = x + r["floorAhead"] / 10 * math.cos(th), y + r["floorAhead"] / 10 * math.sin(th)
    col = 2 if 120 <= fx <= 126 else 0 if (150 <= fx <= 205 and 30 <= fy <= 80) else 6  # blue tape, red mat, white floor
    return ir, col


class FakeEV3:
    """A stand-in for DS4Receiver on 127.0.0.1:5000, for testing without the brick."""

    def __init__(self):
        self.lock = threading.Lock()
        self.srv = None
        self.motors = (0, 0, 0)
        self.last_at = 0.0
        self.lines = 0
        self.clients = 0

    def start(self):
        if self.srv:
            return None
        try:
            srv = socket.socket()
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", EV3_PORT))
            srv.listen(2)
        except OSError as e:
            return f"can't start fake EV3 on port {EV3_PORT}: {e.strerror or e}"
        self.srv = srv
        threading.Thread(target=self._accept, args=(srv,), daemon=True).start()
        return None

    def stop(self):
        srv, self.srv = self.srv, None
        if srv:
            srv.close()

    def _accept(self, srv):
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn):
        """Simulates the receiver: a robot with a medium motor on A, large motors on B and C,
        a touch sensor on 1, a colour sensor on 3 facing the floor and an infrared sensor on 4
        facing ahead, in a small room (PRACTICE_ROOM). Understands mapping lines (P), tests (M)
        and the old format."""
        with self.lock:
            self.clients += 1
        buf = b""
        conn.settimeout(0.05)
        try:
            conn.sendall(f"V {version.__version__}\n".encode())  # like the real receiver
        except OSError:
            return
        last_t = time.monotonic()
        last_status = 0.0
        tacho = {"A": 0.0, "B": 0.0, "C": 0.0}
        speeds = {"A": 0.0, "B": 0.0, "C": 0.0}
        max_dps = {"A": 1300.0, "B": 900.0, "C": 900.0}  # roughly medium / large motor top speed
        tests = {}  # port -> {"pct", "until"} for held runs, or {"pct", "left"} for exact turns
        pcmd, pcmd_at = {}, 0.0  # latest mapping line
        truth = worldmap.Odometry()  # the pretend robot's real position, for its sensors
        try:
            while self.srv:
                now = time.monotonic()
                dt, last_t = now - last_t, now
                with self.lock:
                    legacy = self.motors if now - self.last_at < 0.5 else None
                mapped = now - pcmd_at < 0.5
                for k in tacho:
                    t = tests.get(k)
                    if t and "until" in t and now > t["until"]:
                        tests.pop(k)
                        t = None
                    if t:
                        v = t["pct"] / 100 * max_dps[k]
                        if "left" in t:
                            step = min(abs(v * dt), abs(t["left"]))
                            v = (step / dt if dt else 0) * (1 if t["left"] > 0 else -1)
                            t["left"] -= v * dt
                            if abs(t["left"]) < 0.5:
                                tests.pop(k)
                    elif mapped and pcmd.get(k):
                        c = pcmd[k]
                        if c[0] == "s":
                            v = c[1] / 100 * max_dps[k]
                        else:  # turn to an angle and hold it
                            err = c[1] - tacho[k]
                            top = c[2] / 100 * max_dps[k]
                            v = max(-top, min(top, err / dt if dt else 0))
                    elif legacy and not mapped:
                        v = {"B": legacy[0], "C": legacy[1], "A": legacy[2]}[k] / 100 * max_dps[k]
                    else:
                        v = 0.0
                    speeds[k] = v
                    tacho[k] += v * dt
                # where the pretend robot really is in the practice room, using the default robot size
                if any(c[0] == "p" for c in pcmd.values()):
                    steer = next(k for k, c in sorted(pcmd.items()) if c[0] == "p")
                    lay = {"type": "car", "drive": {k: 1 for k, c in pcmd.items() if c[0] == "s"}, "steer": (steer, 1)}
                else:
                    lay = {"type": "tank", "left": {"B": 1}, "right": {"C": 1}}
                truth.update(dict(tacho), lay, worldmap.ROBOT)
                if now - last_status >= 0.25:
                    # Same status line the real receiver sends.
                    last_status = now
                    load = sum(abs(speeds[k]) / max_dps[k] for k in speeds) / 3
                    volts = 8.35 - 0.4 * load
                    motors = " ".join(f"m{k}={int(tacho[k])}:{int(speeds[k])}:0:-" for k in ("A", "B", "C"))
                    ir, col = practice_sensors(truth.x, truth.y, truth.th)
                    conn.sendall((f"T {volts:.2f} {0.15 + 0.6 * load:.3f} {0.55 * load:.3f} "
                                  "A=125:8h B=125:7h C=125:7h D=126:126 1=121:16 2=126:126 3=122:29h 4=122:33h "
                                  f"{motors} s3=col:{col} s4=ir:{ir}\n").encode())
                    with self.lock:
                        self.motors_now = {k: round(speeds[k] / max_dps[k] * 100) for k in speeds}
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    break
                buf += data
                *lines, buf = buf.split(b"\n")
                for line in lines:
                    p = line.decode("ascii", "replace").split()
                    if len(p) >= 3 and p[0] == "M":
                        port, action = p[1], p[2]
                        val = int(p[3]) if len(p) > 3 else 0
                        spd = int(p[4]) if len(p) > 4 else 50
                        if port == "*" or action == "stop":
                            for k in ([port] if port in tacho else list(tacho)):
                                tests.pop(k, None)
                        elif port in tacho and action == "zero":
                            tacho[port] = 0.0
                        elif port in tacho and action == "run":
                            tests[port] = {"pct": clamp100(val), "until": now + 0.4}
                        elif port in tacho and action == "rotate":
                            tests[port] = {"pct": abs(clamp100(spd)), "left": float(val)}
                        continue
                    if p and p[0] == "P":
                        pcmd = {}
                        for item in p[1:]:
                            k, _, v = item.partition("=")
                            parts = v.split(":")
                            try:
                                if parts[0] == "s":
                                    pcmd[k] = ("s", int(parts[1]))
                                elif parts[0] == "p":
                                    pcmd[k] = ("p", int(parts[1]), int(parts[2]))
                            except (IndexError, ValueError):
                                pass
                        pcmd_at = now
                        with self.lock:
                            self.last_at = now
                            self.lines += 1
                        continue
                    if len(p) == 3:
                        try:
                            vals = tuple(clamp100(int(x)) for x in p)
                        except ValueError:
                            continue
                        with self.lock:
                            self.motors, self.last_at = vals, now
                            self.lines += 1
        except OSError:
            pass
        finally:
            conn.close()
            with self.lock:
                self.clients -= 1

    def status(self):
        with self.lock:
            fresh = time.monotonic() - self.last_at < 0.5  # same watchdog as the brick
            return {
                "running": self.srv is not None,
                "motors": list(self.motors if fresh else (0, 0, 0)),
                "watchdog": not fresh,
                "lines": self.lines,
                "clients": self.clients,
            }


def probe(host, timeout=0.6):
    """Checks SSH (22) and the DS4Receiver port (5000) on one host."""
    out = {"host": host, "ssh": False, "dropbear": False, "receiver": False, "banner": None}
    try:
        with socket.create_connection((host, 22), timeout=timeout) as s:
            out["ssh"] = True
            s.settimeout(timeout)
            try:
                banner = s.recv(64).split(b"\r\n")[0].decode("ascii", "replace").strip()
                out["banner"] = banner
                out["dropbear"] = "dropbear" in banner.lower()
            except OSError:
                pass
    except OSError:
        pass
    try:
        with socket.create_connection((host, EV3_PORT), timeout=timeout):
            out["receiver"] = True
    except OSError:
        pass
    return out


BT_QUERY = r"""
$ErrorActionPreference = 'SilentlyContinue'
$a = Get-NetAdapter -IncludeHidden | Where-Object { $_.InterfaceDescription -match 'Bluetooth.*(Personal Area|PAN)' } | Select-Object -First 1
$ips = @()
if ($a) { $ips = @(Get-NetIPAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv4 | ForEach-Object IPAddress) }
$radio = Get-PnpDevice -Class Bluetooth -Status OK | Where-Object { $_.FriendlyName -match 'Bluetooth' -and $_.InstanceId -notmatch '^BTHENUM|^BTHLE' } | Select-Object -First 1
$ev3 = @(Get-PnpDevice -Class Bluetooth | Where-Object { $_.FriendlyName -match '^EV3' -and $_.InstanceId -match 'DEV_([0-9A-F]{12})' } | ForEach-Object {
    $m = [regex]::Match($_.InstanceId, 'DEV_([0-9A-F]{12})').Groups[1].Value
    @{ name = $_.FriendlyName; mac = ($m -replace '(..)(?!$)', '$1:'); present = ($_.Status -eq 'OK') } })
# Sony game controllers Windows has connected right now (Bluetooth HID ids contain the 1124 service)
$pads = @(Get-PnpDevice -PresentOnly -Class HIDClass | Where-Object { $_.InstanceId -match 'VID&0002054C|VID_054C' -and $_.FriendlyName -match 'game controller' } | ForEach-Object {
    $id = [regex]::Match($_.InstanceId, 'PID[&_]([0-9A-F]{4})').Groups[1].Value
    @{ pid = $id; via = $(if ($_.InstanceId -match '00001124') { 'Bluetooth' } else { 'USB' }) } })
$padPaired = [bool](Get-PnpDevice -Class Bluetooth | Where-Object { $_.FriendlyName -eq 'Wireless Controller' })
@{ radio = [bool]$radio; adapter = [bool]$a; linkUp = ($a -and $a.Status -eq 'Up'); ips = $ips; bricks = $ev3; pads = $pads; padPaired = $padPaired } | ConvertTo-Json -Compress -Depth 4
"""


DS4_LOCK = threading.Lock()  # one controller read at a time


class Bluetooth:
    """Windows' view of the brick over Bluetooth: paired? network link (PAN) up? brick answering?"""

    def __init__(self):
        self.lock = threading.Lock()
        self.cache = None
        self.at = 0.0
        self.busy = False

    def status(self, max_age=3.0):
        """Returns the last result at once; refreshes in the background (the query takes a few seconds)."""
        with self.lock:
            stale = not self.cache or time.monotonic() - self.at > max_age
            if stale and not self.busy:
                self.busy = True
                threading.Thread(target=self._refresh, daemon=True).start()
            return self.cache or {"loading": True}

    def _refresh(self):
        try:
            data = self._query()
        finally:
            with self.lock:
                self.busy = False
        with self.lock:
            self.cache, self.at = data, time.monotonic()

    def local_ips(self):
        with self.lock:
            return set((self.cache or {}).get("ips") or [])

    @staticmethod
    def _query():
        try:
            p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", BT_QUERY],
                               capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            d = json.loads(p.stdout.strip() or "{}")
        except (subprocess.TimeoutExpired, ValueError, OSError) as e:
            return {"error": f"couldn't read Bluetooth status: {e}"}
        if isinstance(d.get("ips"), str):
            d["ips"] = [d["ips"]]
        if isinstance(d.get("bricks"), dict):
            d["bricks"] = [d["bricks"]]
        if isinstance(d.get("pads"), dict):
            d["pads"] = [d["pads"]]
        d["brickAnswers"] = False
        if d.get("linkUp"):
            try:
                with socket.create_connection((LEJOS_PAN_IP, 22), timeout=0.8):
                    d["brickAnswers"] = True
            except OSError:
                pass
        d["brickIp"] = LEJOS_PAN_IP
        return d

    @staticmethod
    def open_windows_panel():
        # Classic "Devices and Printers": right-click EV3 > Connect using > Access point.
        # (The old "Bluetooth Devices" shell folder is empty on Windows 11.)
        subprocess.Popen(["explorer.exe", "shell:::{A8A91A66-3A7D-4424-8D24-04E180695C7A}"])


class BrickInfo:
    """Cached brick details (SSH + leJOS menu) and port scan, refreshed in the background."""

    def __init__(self):
        self.lock = threading.Lock()
        self.host = None
        self.details = None
        self.details_at = 0.0
        self.details_busy = False
        self.ports = None
        self.ports_at = None
        self.ports_busy = False
        self.ports_error = None

    def get(self, host, max_age=12.0):
        with self.lock:
            if not host:
                # The page doesn't know the address yet (just loaded): show what we have.
                host = self.host
            elif host != self.host:
                self.host, self.details, self.ports, self.ports_at, self.ports_error = host, None, None, None, None
            if host and not self.details_busy and time.monotonic() - self.details_at > max_age:
                self.details_busy = True
                threading.Thread(target=self._refresh, args=(host,), daemon=True).start()
            return {"host": host, "details": self.details, "busy": self.details_busy,
                    "ports": self.ports, "portsAt": self.ports_at, "portsBusy": self.ports_busy,
                    "portsError": self.ports_error}

    def refresh_soon(self):
        with self.lock:
            self.details_at = 0.0

    def _refresh(self, host):
        try:
            d = ev3_brick.details(host)
        except Exception as e:  # noqa: BLE001 - report anything to the page
            d = {"ok": False, "error": str(e)}
        with self.lock:
            if host == self.host:
                self.details, self.details_at = d, time.monotonic()
            self.details_busy = False
            # Live port readings come from the receiver while it runs. Otherwise check the
            # ports ourselves about once a minute (each check starts Java on the brick: ~30 s).
            stale = self.ports_at is None or time.time() - self.ports_at > PORT_CHECK_EVERY_S
            want_probe = d.get("ok") and not d.get("receiverListening") and stale and not self.ports_busy
        if want_probe:
            self.scan_ports(host)

    def scan_ports(self, host):
        with self.lock:
            if self.ports_busy:
                return
            self.ports_busy, self.ports_error = True, None
        threading.Thread(target=self._ports, args=(host,), daemon=True).start()

    def _ports(self, host):
        try:
            p, err = ev3_brick.ports(host), None
        except Exception as e:  # noqa: BLE001
            p, err = None, str(e)
        with self.lock:
            if host == self.host:
                if p is not None:
                    self.ports, self.ports_at = p, time.time()
                self.ports_error = err
            self.ports_busy = False


def link_kind(local_ip, bt_ips):
    if not local_ip:
        return None
    if local_ip.startswith("127."):
        return "practice"
    if local_ip in bt_ips:
        return "Bluetooth"
    if local_ip.startswith("10.0.1."):
        return "USB or Bluetooth"
    return "WiFi"


def local_subnets():
    nets = set()
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            addr = ipaddress.ip_address(ip)
            if addr.is_private and not addr.is_loopback and not addr.is_link_local:
                nets.add(ipaddress.ip_network(f"{ip}/24", strict=False))
    except OSError:
        pass
    return sorted(nets, key=str)


def scan():
    """Looks for SSH servers on this laptop's /24 networks; leJOS runs dropbear."""
    nets = local_subnets()
    hosts = [LEJOS_PAN_IP] + [str(h) for n in nets for h in n.hosts()]
    found = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=128) as ex:
        for r in ex.map(lambda h: probe(h, 0.35), dict.fromkeys(hosts)):
            if r["ssh"] or r["receiver"]:
                found.append(r)
    found.sort(key=lambda r: (not r["dropbear"], not r["receiver"], ipaddress.ip_address(r["host"])))
    return {"networks": [str(n) for n in nets], "found": found}


def build_upload(lejos_home, host):
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
           os.path.join(ROOT, "build.ps1")]
    if lejos_home:
        cmd += ["-LejosHome", lejos_home]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=ROOT,
                           stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return {"ok": False, "log": "build timed out after 5 minutes"}
    log = (p.stdout + p.stderr).strip()
    if p.returncode != 0 or not host:
        return {"ok": p.returncode == 0, "log": log}
    try:
        sent = ev3_brick.upload(host)
    except ev3_brick.BrickError as e:
        return {"ok": False, "log": log + f"\nupload failed: {e}"}
    brick.refresh_soon()
    return {"ok": True, "log": log + "\n" + "\n".join(f"uploaded {j} to {host}" for j in sent)}


link = Link()
fake = FakeEV3()
bt = Bluetooth()
brick = BrickInfo()
cam = camera.Camera()
see = vision.Vision(cam, on_result=link.world.see)  # object recognition, optional (pc/vision.py); found things go on the map


class Handler(BaseHTTPRequestHandler):
    server_version = "PowerShock/" + version.__version__

    def log_message(self, fmt, *args):
        pass  # quiet; the page polls often

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _camera_stream(self):
        """Relays the Pi's live video; the page shows it in an <img>."""
        started = []

        def start(ctype):
            started.append(True)
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        try:
            cam.relay(self.wfile, start)
        except camera.CameraError as e:
            if not started:
                self._json({"error": str(e)}, 502)
        self.close_connection = True

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if not 0 < n <= 65536:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except ValueError:
            return {}

    def _local_only(self):
        """Refuse other machines, other websites and DNS-rebinding tricks.
        - the connection must come from this laptop
        - the Host header must be this console (a rebound attacker.com name fails here)
        - a browser Origin, if sent, must be this console exactly
        - /api/* also needs our X-PowerShock header (set by the page; other sites can't add
          it without a CORS preflight we never answer) or a same-origin fetch, so an <img> or
          link on another site can't trigger anything."""
        here = {f"127.0.0.1:{HTTP_PORT}", f"localhost:{HTTP_PORT}"}
        if self.client_address[0] not in ("127.0.0.1", "::1") or self.headers.get("Host", "") not in here:
            self._json({"error": "local only"}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {"http://" + h for h in here}:
            self._json({"error": "bad origin"}, 403)
            return False
        if self.path.startswith("/api/") and self.headers.get("X-PowerShock") != "1" \
                and self.headers.get("Sec-Fetch-Site") != "same-origin":
            self._json({"error": "missing X-PowerShock header"}, 403)
            return False
        return True

    def do_GET(self):
        if not self._local_only():
            return
        if self.path in ("/", "/index.html", "/camera"):
            # /camera: just the robot's camera, in a window of its own (for a second monitor)
            with open(UI_FILE if self.path != "/camera" else CAM_FILE, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.split("?")[0].endswith(".js") and not self.path.startswith("/api/"):
            # Scripts next to the page (the 3D controller) and vendored libraries (three.js).
            base = os.path.realpath(os.path.dirname(UI_FILE))
            path = os.path.realpath(os.path.join(base, self.path.split("?")[0].lstrip("/")))
            if not path.startswith(base + os.sep) or not os.path.isfile(path):
                return self._json({"error": "not found"}, 404)
            with open(path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            ls = link.status()
            ls["via"] = link_kind(ls.get("localIp"), bt.local_ips())
            self._json({"link": ls, "fake": fake.status(), "app": {"version": version.__version__}})
        elif self.path == "/api/mapping":
            with link.lock:
                current = link.mapper.mapping
            self._json({"mapping": current, "presets": mapping.PRESETS})
        elif self.path == "/api/bluetooth":
            self._json(bt.status())
        elif self.path == "/api/map":
            self._json(link.world.snapshot())
        elif self.path == "/api/camera":
            self._json(cam.status())
        elif self.path == "/api/vision":
            self._json(see.status())
        elif self.path.split("?")[0] == "/api/camera/stream":
            self._camera_stream()
        elif self.path.split("?")[0] == "/api/camera/snapshot":
            try:
                jpeg = cam.snapshot()
            except camera.CameraError as e:
                return self._json({"error": str(e)}, 502)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(jpeg)))
            self.end_headers()
            self.wfile.write(jpeg)
        elif self.path == "/api/ds4":
            # battery, model and firmware straight from Windows; no browser device picker needed
            with DS4_LOCK:
                self._json(ds4_hid.read())
        elif self.path.startswith("/api/brick"):
            from urllib.parse import parse_qs, urlparse
            host = (parse_qs(urlparse(self.path).query).get("host") or [""])[0].strip()
            self._json(brick.get(host or None))
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._local_only():
            return
        b = self._body()
        if self.path == "/api/input":
            # Raw controller (or keyboard) state from the page; the mapping does the rest.
            try:
                inp = {k: float(b.get(k, 0)) for k in ("lx", "ly", "rx", "ry", "l2", "r2")}
            except (TypeError, ValueError):
                return self._json({"ok": False, "error": "bad input"})
            inp["stop"] = bool(b.get("stop"))
            inp["pad"] = b.get("src", "pad") == "pad"  # calibration is for the real controller only
            link.set_input(inp)
            self._json({"ok": True})
        elif self.path == "/api/mapping":
            try:
                m = mapping.validate(b.get("mapping"))
            except (TypeError, ValueError) as e:
                return self._json({"ok": False, "error": str(e)})
            mapping.save(m)
            link.set_mapping(m)
            self._json({"ok": True, "mapping": m})
        elif self.path == "/api/test":
            # One motor at a time: {"port": "D", "action": "run|rotate|stop", "value": n, "speed": pct}
            port = str(b.get("port", "")).upper()
            action = str(b.get("action", ""))
            if port not in ("A", "B", "C", "D", "*") or action not in ("run", "rotate", "stop", "zero"):
                return self._json({"ok": False, "error": "bad test command"})
            try:
                value = max(-3600, min(3600, int(b.get("value") or 0)))
                speed = max(5, min(100, int(b.get("speed") or 50)))
            except (TypeError, ValueError):
                return self._json({"ok": False, "error": "bad test command"})
            ok = link.send_line(f"M {port} {action} {value} {speed}")
            self._json({"ok": ok, "error": None if ok else "not connected to PowerShock"})
        elif self.path == "/api/stop":
            link.stop_input()
            link.send_line("M * stop 0 50")  # also ends any motor test in progress
            self._json({"ok": True})
        elif self.path == "/api/connect":
            host = str(b.get("host", "")).strip()
            if not host:
                return self._json({"ok": False, "error": "enter the EV3 IP address"})
            ok = link.connect(host)
            self._json({"ok": ok, "error": link.status()["error"]})
        elif self.path == "/api/disconnect":
            link.disconnect()
            self._json({"ok": True})
        elif self.path == "/api/probe":
            host = str(b.get("host", "")).strip()
            self._json(probe(host, 1.0) if host else {"error": "no host"})
        elif self.path == "/api/scan":
            self._json(scan())
        elif self.path == "/api/bluetooth/open":
            Bluetooth.open_windows_panel()
            self._json({"ok": True})
        elif self.path == "/api/camera":
            try:
                cam.set(b.get("host"), b.get("port", 8080), b.get("key"))
            except camera.CameraError as e:
                return self._json({"ok": False, "error": str(e)})
            except OSError as e:
                return self._json({"ok": False, "error": f"Couldn't save the camera settings: {e.strerror or e}"})
            st = cam.status(max_age=0)
            self._json({"ok": True, "status": st})
        elif self.path == "/api/vision":
            # {"on": true} while the Camera view shows recognition (it stops a few seconds after the
            # last one), {"on": false} when the page is done. Answers with what was found.
            on = b.get("on")
            if not isinstance(on, bool):
                return self._json({"ok": False, "error": "bad vision command"})
            self._json(see.poll(on))
        elif self.path == "/api/camera/forget":
            cam.forget()
            self._json({"ok": True})
        elif self.path == "/api/map/reset":
            link.world.reset()
            self._json({"ok": True})
        elif self.path == "/api/map/robot":
            self._json({"ok": True, "robot": link.world.set_robot(b.get("robot"))})
        elif self.path == "/api/fake":
            if b.get("on"):
                err = fake.start()
                self._json({"ok": err is None, "error": err})
            else:
                fake.stop()
                self._json({"ok": True})
        elif self.path in ("/api/brick/ports", "/api/brick/run", "/api/brick/stop",
                           "/api/wifi/scan", "/api/wifi/join"):
            host = str(b.get("host", "")).strip()
            if not host:
                return self._json({"ok": False, "error": "no brick address"})
            try:
                if self.path == "/api/brick/ports":
                    brick.scan_ports(host)
                    r = {"ok": True}
                elif self.path == "/api/brick/run":
                    r = ev3_brick.run(host, "powershock-wifi.jar")
                elif self.path == "/api/brick/stop":
                    link.set_input(None)
                    r = ev3_brick.stop(host)
                elif self.path == "/api/wifi/scan":
                    r = {"ok": True, "networks": ev3_brick.wifi_scan(host)}
                else:
                    # The password goes straight into the key derivation and is never logged.
                    r = ev3_brick.wifi_join(host, str(b.get("ssid", "")), str(b.get("password", "")))
            except ev3_brick.BrickError as e:
                r = {"ok": False, "error": str(e)}
            if self.path != "/api/wifi/scan":
                brick.refresh_soon()
            self._json(r)
        elif self.path == "/api/build":
            self._json(build_upload("", str(b.get("host", "")).strip()))
        else:
            self._json({"error": "not found"}, 404)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), Handler)
    srv.daemon_threads = True
    url = f"http://127.0.0.1:{HTTP_PORT}/"
    print(f"PowerShock Console at {url}  (Ctrl+C to quit)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        link.disconnect()
        fake.stop()


if __name__ == "__main__":
    main()
