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
}
LIMITS = {"wheel": (20, 200), "track": (40, 400), "base": (40, 400), "steerRatio": (0.05, 3.0),
          "eyeAhead": (-300, 300), "eyeAngle": (-180, 180), "floorAhead": (-300, 300)}

IR_RANGE = 70.0   # cm at proximity 100; the EV3 IR sensor is roughly linear up to here
IR_NOTHING = 95   # proximity at or above this: nothing in range
US_RANGE = 150.0  # cm; ultrasonic readings beyond this are too wide to place well


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


class Odometry:
    """Dead reckoning from wheel motor angles."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.x = self.y = self.th = 0.0
        self.last = None
        self.gyro0 = None
        self.th0 = 0.0

    def relink(self):
        """The brick program restarted: its motor angles start again from 0."""
        self.last = None
        self.gyro0 = None

    def update(self, tachos, lay, robot, gyro=None):
        """tachos: {port: degrees}. Returns the distance moved (cm)."""
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
            self.eye = None  # last range reading: {"dist", "hit", "kind"}
            self.updates = 0
            self.lay = None

    def relink(self):
        with self.lock:
            self.odo.relink()

    def feed(self, telemetry, mapping):
        """One status line from the brick (see ev3_brick.parse_telemetry)."""
        if not telemetry:
            return
        lay = layout(mapping)
        motors = telemetry.get("motors") or {}
        sensors = telemetry.get("sensors") or {}
        with self.lock:
            r = self.robot
            gyro = next((s["value"] for s in sensors.values() if s["kind"] == "gy"), None)
            self.odo.update({p: m["tacho"] for p, m in motors.items()}, lay, r, gyro)
            self.lay, self.sensors, self.updates = lay, sensors, self.updates + 1
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
                    self.eye = {"dist": round(dist, 1), "hit": hit, "kind": s["kind"]}
                elif s["kind"] == "col" and s["value"] >= 0:
                    ahead = r["floorAhead"] / 10
                    self.grid.paint(o.x + ahead * math.cos(o.th), o.y + ahead * math.sin(o.th), s["value"])

    def snapshot(self):
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
                "eye": self.eye,
                "updates": self.updates,
            }
