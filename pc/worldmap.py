"""A live map of what the robot has seen, built on the laptop while it drives.

Two parts:
- Where the robot is (odometry): from the wheel motors' angles, which the brick reports 4 times
  a second, the robot's size, and the steering motor's angle (car) or the difference between
  the left and right wheels (tank). A gyro sensor, if plugged in, gives the heading instead.
  This drifts: every slip of a wheel is an error that never goes away.
- What is around it (an occupancy grid): the infrared or ultrasonic sensor, facing forward,
  says how far away the nearest thing is. Cells along that line are probably free, the cell at
  the end is probably taken. Each cell keeps a running score (log-odds), so one bad reading
  doesn't draw a wall. The colour sensor, facing the floor, paints the floor's colour.

Units: centimetres and radians; x is forward from where the map started, y is to the left,
the heading turns anticlockwise. The robot's size is in millimetres, as LEGO parts are.
"""
import json
import math
import os
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "worldmap.json")

CELL = 4.0  # cm per grid cell
SIZE = 201  # cells per side: 8 m x 8 m, centred where the map started
LO_FREE, LO_HIT, LO_MIN, LO_MAX = -0.4, 0.9, -4.0, 4.0
SHOW = 0.6  # cells scoring above this are drawn as obstacles
TRAIL_MAX = 3000

# The robot's size and where its sensors sit. Defaults fit a small EV3 car or tank.
ROBOT = {
    "wheel": 56.0,       # wheel diameter, mm
    "track": 120.0,      # distance between the left and right wheels, mm (tank turning)
    "base": 140.0,       # distance between front and rear axles, mm (car turning)
    "steerRatio": 1.0,   # degrees the front wheels turn per degree of the steering motor
    "eyeAhead": 60.0,    # infrared / ultrasonic sensor: mm ahead of the driven axle
    "eyeAngle": 0.0,     # ... and which way it faces: 0 = ahead, 90 = left, -90 = right
    "floorAhead": 40.0,  # colour sensor: mm ahead of the driven axle
    "gyroSign": 1,       # 1 if the gyro counts anticlockwise turns as positive, -1 if not
    "camAhead": 40.0,    # Raspberry Pi camera: mm ahead of the driven axle
    "camHeight": 150.0,  # ... mm above the floor
    "camTilt": 15.0,     # ... degrees it looks down (0 = level)
    "camFov": 62.0,      # ... degrees it sees across (62 for the Pi camera v2, 54 for v1)
}
LIMITS = {"wheel": (20, 200), "track": (40, 400), "base": (40, 400), "steerRatio": (0.05, 3.0),
          "eyeAhead": (-300, 300), "eyeAngle": (-180, 180), "floorAhead": (-300, 300),
          "camAhead": (-300, 300), "camHeight": (30, 600), "camTilt": (-10, 60), "camFov": (30, 160)}

IR_RANGE = 70.0   # cm at proximity 100; the EV3 IR sensor is roughly linear up to here
IR_NOTHING = 95   # proximity at or above this: nothing in range
US_RANGE = 150.0  # cm; ultrasonic readings beyond this are too wide to place well

# Things the camera recognises, placed on the map
SEE_SCORE = 0.5     # recognitions less sure than this aren't placed
SEE_FAR = 400.0     # cm; anything placed further away than this is too uncertain
SEE_KEEP = 50       # most things kept on the map
SEE_SHOW = 2        # seen this many times before it's shown, so one wrong guess isn't drawn
SEE_MISSES = 15     # in view this many times without being seen: it has gone (a person walked off)
IR_CONE = 12.0      # degrees either side of the IR sensor's line where its distance is used instead


def robot_settings(d):
    """Checked robot settings: unknown keys dropped, numbers kept in range."""
    out = dict(ROBOT)
    for k, (lo, hi) in LIMITS.items():
        try:
            out[k] = max(lo, min(hi, float(d.get(k, out[k]))))
        except (TypeError, ValueError, AttributeError):
            pass
    try:
        out["gyroSign"] = -1 if int(d.get("gyroSign", 1)) < 0 else 1
    except (TypeError, ValueError, AttributeError):
        pass
    return out


def layout(mapping):
    """Which ports move the robot, from the controls mapping:
    {"type": "tank", "left": {port: sign}, "right": {port: sign}} or
    {"type": "car", "drive": {port: sign}, "steer": (port, sign) | None} or None."""
    ports = (mapping or {}).get("ports") or {}
    sign = lambda c: -1 if c.get("invert") else 1  # noqa: E731
    left = {p: sign(c) for p, c in ports.items() if c.get("mode") == "drive" and c.get("side") == "left"}
    right = {p: sign(c) for p, c in ports.items() if c.get("mode") == "drive" and c.get("side") == "right"}
    if left and right:
        return {"type": "tank", "left": left, "right": right}
    throttle = ((mapping or {}).get("drive") or {}).get("throttle")
    speed = {p: c for p, c in ports.items() if c.get("mode") == "speed"}
    drive = {p: sign(c) for p, c in speed.items() if c.get("input") == throttle} or {p: sign(c) for p, c in speed.items()}
    if not drive:
        return None
    steer = next(((p, sign(c)) for p, c in sorted(ports.items()) if c.get("mode") == "position"), None)
    return {"type": "car", "drive": drive, "steer": steer}


def forward_speed(speeds, lay, robot):
    """cm/s forward (negative: backwards) from the drive motors' speeds in degrees a second."""
    if not lay:
        return 0.0
    cm_per_deg = math.pi * robot["wheel"] / 10 / 360
    groups = (lay["left"], lay["right"]) if lay["type"] == "tank" else (lay["drive"],)
    means = [sum(speeds.get(p, 0) * s for p, s in g.items()) / len(g) for g in groups if g]
    return sum(means) / len(means) * cm_per_deg if means else 0.0


class Odometry:
    """Dead reckoning from wheel motor angles."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.x = self.y = self.th = 0.0
        self.last = None
        self.gyro0 = None
        self.th0 = 0.0
        self.ds = 0.0  # cm driven in the last update, forward positive

    def relink(self):
        """The brick program restarted: its motor angles start again from 0."""
        self.last = None
        self.gyro0 = None

    def update(self, tachos, lay, robot, gyro=None):
        """tachos: {port: degrees}. Returns the distance moved (cm)."""
        self.ds = 0.0
        if self.last is None:
            self.last = dict(tachos)
            if gyro is not None:
                self.gyro0, self.th0 = gyro, self.th
            return 0.0
        d = {p: tachos[p] - self.last.get(p, tachos[p]) for p in tachos}
        self.last = dict(tachos)
        if not lay:
            return 0.0
        cm_per_deg = math.pi * robot["wheel"] / 10 / 360
        mean = lambda ports: sum(d.get(p, 0) * s for p, s in ports.items()) / max(1, len(ports))  # noqa: E731
        if lay["type"] == "tank":
            dl, dr = mean(lay["left"]) * cm_per_deg, mean(lay["right"]) * cm_per_deg
            ds, dth = (dl + dr) / 2, (dr - dl) / (robot["track"] / 10)
        else:
            ds = mean(lay["drive"]) * cm_per_deg
            dth = 0.0
            if lay["steer"] and lay["steer"][0] in tachos:
                port, s = lay["steer"]
                wheels = math.radians(max(-80.0, min(80.0, tachos[port] * s * robot["steerRatio"])))
                dth = -ds * math.tan(wheels) / (robot["base"] / 10)  # steering right turns clockwise
        if gyro is not None:
            if self.gyro0 is None:
                self.gyro0, self.th0 = gyro, self.th
            new_th = self.th0 + math.radians((gyro - self.gyro0) * robot["gyroSign"])
            dth = new_th - self.th
        self.ds = ds
        mid = self.th + dth / 2
        self.x += ds * math.cos(mid)
        self.y += ds * math.sin(mid)
        self.th += dth
        return abs(ds)


class Grid:
    """Occupancy grid: a log-odds score per cell, plus floor colours."""

    def __init__(self, cell=CELL, size=SIZE):
        self.cell, self.size, self.half = cell, size, size // 2
        self.lo = [0.0] * (size * size)
        self.touched = set()  # cells with any score, so listing them stays quick
        self.floor = {}

    def index(self, x, y):
        i, j = int(round(x / self.cell)) + self.half, int(round(y / self.cell)) + self.half
        return (i, j) if 0 <= i < self.size and 0 <= j < self.size else None

    def _add(self, ij, v):
        k = ij[0] * self.size + ij[1]
        self.lo[k] = max(LO_MIN, min(LO_MAX, self.lo[k] + v))
        self.touched.add(k)

    def ray(self, x, y, th, dist, hit):
        """A range reading from (x, y) facing th: free up to dist, and taken at dist if hit."""
        end = self.index(x + dist * math.cos(th), y + dist * math.sin(th)) if hit else None
        seen = set()
        steps = int(dist / (self.cell / 2))
        for n in range(steps):
            r = n * self.cell / 2
            ij = self.index(x + r * math.cos(th), y + r * math.sin(th))
            if ij is None or ij == end or ij in seen:
                continue
            seen.add(ij)
            self._add(ij, LO_FREE)
        if end is not None:
            self._add(end, LO_HIT)

    def paint(self, x, y, colour):
        ij = self.index(x, y)
        if ij is not None:
            self.floor[ij] = colour

    def cells(self):
        """[[i, j, score], ...] for cells that look taken; i, j relative to the start."""
        out = []
        for k in sorted(self.touched):
            v = self.lo[k]
            if v > SHOW:
                out.append([k // self.size - self.half, k % self.size - self.half, round(v, 1)])
        return out


class WorldMap:
    def __init__(self, config=CONFIG):
        self.lock = threading.Lock()
        self.config = config
        self.robot = self._load()
        self.reset()

    def _load(self):
        try:
            with open(self.config, encoding="utf-8") as f:
                return robot_settings(json.load(f))
        except (OSError, ValueError):
            return dict(ROBOT)

    def set_robot(self, d):
        r = robot_settings(d if isinstance(d, dict) else {})
        with self.lock:
            self.robot = r
        try:
            with open(self.config, "w", encoding="utf-8") as f:
                json.dump(r, f, indent=2)
        except OSError:
            pass
        return r

    def reset(self):
        with self.lock:
            self.odo = Odometry()
            self.grid = Grid()
            self.trail = [[0.0, 0.0]]
            self.sensors = {}
            self.eye = None  # last range reading: {"dist", "hit", "kind", "at", "speed"}
            self.updates = 0
            self.lay = None
            self.speed = 0.0  # cm/s forward, from the speeds the brick measures at the wheels
            self.objects = []  # what the camera recognised: {"label", "x", "y", "n", "seen", "miss"}

    def relink(self):
        with self.lock:
            self.odo.relink()

    def feed(self, telemetry, mapping, now=None):
        """One status line from the brick (see ev3_brick.parse_telemetry)."""
        if not telemetry:
            return
        now = time.monotonic() if now is None else now
        lay = layout(mapping)
        motors = telemetry.get("motors") or {}
        sensors = telemetry.get("sensors") or {}
        with self.lock:
            r = self.robot
            gyro = next((s["value"] for s in sensors.values() if s["kind"] == "gy"), None)
            self.odo.update({p: m["tacho"] for p, m in motors.items()}, lay, r, gyro)
            self.lay, self.sensors, self.updates = lay, sensors, self.updates + 1
            # the brick's own speed readings, not angle changes between lines: lines can arrive
            # bunched up after a WiFi hiccup, and that would look like a sudden burst of speed
            self.speed = forward_speed({p: m.get("speed", 0) for p, m in motors.items()}, lay, r)
            if not any(s["kind"] in ("ir", "us") for s in sensors.values()):
                self.eye = None  # unplugged
            o = self.odo
            if math.hypot(o.x - self.trail[-1][0], o.y - self.trail[-1][1]) >= 1.0:
                self.trail.append([round(o.x, 1), round(o.y, 1)])
                del self.trail[:-TRAIL_MAX]
            for s in sensors.values():
                if s["kind"] in ("ir", "us"):
                    if s["kind"] == "ir":
                        hit = s["value"] < IR_NOTHING
                        dist = max(0, s["value"]) * IR_RANGE / 100 if hit else IR_RANGE
                    else:
                        hit = 0 < s["value"] <= US_RANGE
                        dist = s["value"] if hit else US_RANGE
                    ahead = r["eyeAhead"] / 10
                    ex, ey = o.x + ahead * math.cos(o.th), o.y + ahead * math.sin(o.th)
                    face = o.th + math.radians(r["eyeAngle"])
                    self.grid.ray(ex, ey, face, dist, hit)
                    self.eye = {"dist": round(dist, 1), "hit": hit, "kind": s["kind"], "at": now,
                                "speed": round(self.speed, 1)}
                elif s["kind"] == "col" and s["value"] >= 0:
                    ahead = r["floorAhead"] / 10
                    self.grid.paint(o.x + ahead * math.cos(o.th), o.y + ahead * math.sin(o.th), s["value"])

    def eye_now(self):
        """The latest range reading for the brake, with the robot's measured speed, and the robot's settings."""
        with self.lock:
            return (dict(self.eye) if self.eye else None), dict(self.robot)

    def see(self, items, now=None):
        """Places what the camera recognised (vision.decode's items) on the map, around the robot.
        Which way: from where the box is across the picture. How far: from where its bottom edge
        meets the floor, given the camera's height and tilt; or the IR sensor's distance, if the
        thing is straight ahead and the sensor sees something there."""
        now = time.monotonic() if now is None else now
        with self.lock:
            r, o, eye = self.robot, self.odo, self.eye
            fov = math.radians(r["camFov"])
            vfov = 2 * math.atan(math.tan(fov / 2) * 3 / 4)  # the camera's pictures are 4:3
            tilt, height = math.radians(r["camTilt"]), r["camHeight"] / 10
            cx, cy = o.x + r["camAhead"] / 10 * math.cos(o.th), o.y + r["camAhead"] / 10 * math.sin(o.th)
            placed = []
            for t in items:
                if t.get("score", 0) < SEE_SCORE:
                    continue
                x0, y0, x1, y1 = t["box"]
                bearing = (0.5 - (x0 + x1) / 2) * fov  # left of centre is positive, like the map's turns
                down = tilt + (min(y1, 1.0) - 0.5) * vfov  # how far below level its bottom edge is
                if down <= math.radians(2):
                    continue  # at or above the horizon: it isn't standing on the floor
                dist = height / math.tan(down)
                ir_ok = eye and eye["hit"] and eye["kind"] == "ir" and now - eye["at"] < 0.5
                if ir_ok and abs(math.degrees(bearing) - r["eyeAngle"]) < IR_CONE:
                    dist = eye["dist"] + (r["eyeAhead"] - r["camAhead"]) / 10
                if not 5 <= dist <= SEE_FAR:
                    continue
                a = o.th + bearing
                placed.append((t["label"], cx + dist * math.cos(a), cy + dist * math.sin(a), dist))
            matched = set()
            for label, x, y, dist in placed:
                near = max(30.0, dist * 0.25)  # far things are placed less exactly
                best = None
                for k, ob in enumerate(self.objects):
                    d = math.hypot(ob["x"] - x, ob["y"] - y)
                    if ob["label"] == label and k not in matched and d < near and (best is None or d < best[1]):
                        best = (k, d)
                if best:
                    ob = self.objects[best[0]]
                    w = 1.0 / min(10, ob["n"] + 1)
                    ob["x"] += (x - ob["x"]) * w
                    ob["y"] += (y - ob["y"]) * w
                    ob["n"], ob["seen"], ob["miss"] = ob["n"] + 1, now, 0
                    matched.add(best[0])
                else:
                    self.objects.append({"label": label, "x": x, "y": y, "n": 1, "seen": now, "miss": 0})
                    matched.add(len(self.objects) - 1)
            # things that should be in view but weren't seen this time: after a while, they've gone
            keep = []
            for k, ob in enumerate(self.objects):
                if k not in matched:
                    dx, dy = ob["x"] - cx, ob["y"] - cy
                    off = (math.atan2(dy, dx) - o.th + math.pi) % (2 * math.pi) - math.pi
                    if abs(off) < fov * 0.4 and math.hypot(dx, dy) < 250:
                        ob["miss"] += 1
                if ob["miss"] < SEE_MISSES:
                    keep.append(ob)
            keep.sort(key=lambda ob: ob["seen"])
            self.objects = keep[-SEE_KEEP:]

    def snapshot(self):
        now = time.monotonic()
        with self.lock:
            o = self.odo
            return {
                "pose": {"x": round(o.x, 1), "y": round(o.y, 1), "heading": round(math.degrees(o.th), 1)},
                "trail": list(self.trail),
                "cells": self.grid.cells(),
                "floor": [[i - self.grid.half, j - self.grid.half, c] for (i, j), c in self.grid.floor.items()],
                "cell": self.grid.cell,
                "robot": dict(self.robot),
                "layout": self.lay["type"] if self.lay else None,
                "sensors": self.sensors,
                "eye": {k: v for k, v in self.eye.items() if k != "at"} if self.eye else None,
                "objects": [{"label": ob["label"], "x": round(ob["x"], 1), "y": round(ob["y"], 1),
                             "seen": round(now - ob["seen"], 1)} for ob in self.objects if ob["n"] >= SEE_SHOW],
                "updates": self.updates,
            }
