"""Controls mapping: which controller input drives which EV3 port, and how.

The console runs this 50 times a second. Each motor port gets one of:

  off       - left alone
  drive     - one side of a two-wheel (tank) drive: throttle +/- steer, mixed
  speed     - an axis sets the motor speed (forward/back)
  position  - an axis sets the motor *angle* (steering, arms): -range..+range degrees

Every port has a smoothing time (seconds from 0 to full). That is what makes car-style
control feel gradual: the throttle ramps up and the steering turns smoothly instead of
jumping. Stopping (X, Stop, or losing input) is always immediate.

Inputs are named: LX, LY, RX, RY (stick axes, Y positive = pushed up), L2, R2 (0..1),
"R2-L2" (gas and brake on the triggers, like driving games), or "none".

Stick feel ("sticks") applies to every stick axis before the ports see it:
  offset    where each axis rests (measured by Calibrate); subtracted so rest reads 0
  span      the furthest each axis reached each way; scaled so full tilt reads exactly 1
  deadzone  percent of travel around the centre that counts as 0 (hides drift)
  curve     0 = linear; up to 100 = gentler near the centre for fine control (expo)
Offset and span are only for a real controller, not the keyboard.
"""

import copy
import json
import os

AXES = ("LX", "LY", "RX", "RY", "L2", "R2", "R2-L2", "none")
MODES = ("off", "drive", "speed", "position")
PORTS = ("A", "B", "C", "D")

TANK = {
    "name": "tank",
    "drive": {"throttle": "LY", "steer": "LX", "turn": 100},
    "speed": {"base": 50, "boost": "R2"},
    "ports": {
        "A": {"mode": "speed", "input": "RY", "invert": False, "max": 100, "smooth": 0.0},
        "B": {"mode": "drive", "side": "left", "invert": False, "max": 100, "smooth": 0.0},
        "C": {"mode": "drive", "side": "right", "invert": False, "max": 100, "smooth": 0.0},
        "D": {"mode": "off"},
    },
}

# Car: the left stick steers (a motor turned to an angle), the right stick is the throttle.
CAR = {
    "name": "car",
    "drive": {"throttle": "RY", "steer": "LX", "turn": 100},
    "speed": {"base": 60, "boost": "R2"},
    "ports": {
        "A": {"mode": "off"},
        "B": {"mode": "speed", "input": "RY", "invert": False, "max": 100, "smooth": 0.8},
        "C": {"mode": "speed", "input": "RY", "invert": False, "max": 100, "smooth": 0.8},
        "D": {"mode": "position", "input": "LX", "invert": False, "range": 45, "speed": 60, "smooth": 0.3},
    },
}

PRESETS = {"tank": TANK, "car": CAR}

STICK_AXES = ("lx", "ly", "rx", "ry")
STICKS = {"deadzone": 8, "curve": 0,
          "offset": {a: 0.0 for a in STICK_AXES},
          "span": {a: [-1.0, 1.0] for a in STICK_AXES}}


def default():
    m = copy.deepcopy(TANK)
    m["sticks"] = copy.deepcopy(STICKS)
    return m


def _sticks(s):
    s = s if isinstance(s, dict) else {}
    off, span = s.get("offset") or {}, s.get("span") or {}
    out = {"deadzone": _num(s.get("deadzone", 8), 0, 40), "curve": _num(s.get("curve", 0), 0, 100), "offset": {}, "span": {}}
    for a in STICK_AXES:
        o = _num(off.get(a, 0.0), -0.3, 0.3)
        lo, hi = (span.get(a) or [-1.0, 1.0])[:2]
        out["offset"][a] = o
        out["span"][a] = [_num(lo, -1.0, o - 0.3), _num(hi, o + 0.3, 1.0)]
    return out


def validate(m):
    """Returns a cleaned copy of a mapping sent by the page, or raises ValueError."""
    if not isinstance(m, dict):
        raise ValueError("mapping must be an object")
    out = {"name": str(m.get("name", "custom"))[:20], "ports": {}, "sticks": _sticks(m.get("sticks"))}
    d = m.get("drive") or {}
    out["drive"] = {"throttle": _axis(d.get("throttle", "LY")), "steer": _axis(d.get("steer", "LX")),
                    "turn": _num(d.get("turn", 100), 0, 100)}
    sp = m.get("speed") or {}
    out["speed"] = {"base": _num(sp.get("base", 50), 10, 100), "boost": _axis(sp.get("boost", "R2"))}
    ports = m.get("ports") or {}
    for p in PORTS:
        c = ports.get(p) or {}
        mode = c.get("mode", "off")
        if mode not in MODES:
            raise ValueError(f"unknown mode for {p}: {mode}")
        pc = {"mode": mode}
        if mode != "off":
            pc["invert"] = bool(c.get("invert", False))
            pc["smooth"] = _num(c.get("smooth", 0), 0, 3)
        if mode == "drive":
            pc["side"] = "right" if c.get("side") == "right" else "left"
            pc["max"] = _num(c.get("max", 100), 0, 100)
        elif mode == "speed":
            pc["input"] = _axis(c.get("input", "RY"))
            pc["max"] = _num(c.get("max", 100), 0, 100)
        elif mode == "position":
            pc["input"] = _axis(c.get("input", "LX"))
            pc["range"] = _num(c.get("range", 45), 5, 720)
            pc["speed"] = _num(c.get("speed", 60), 5, 100)
        out["ports"][p] = pc
    return out


def _axis(a):
    if a not in AXES:
        raise ValueError(f"unknown input: {a}")
    return a


def _num(v, lo, hi):
    v = float(v)
    return max(lo, min(hi, v))


def stick(axis, raw, sticks=None, pad=True):
    """One stick axis, raw -1..1 -> calibrated, dead-zoned and shaped -1..1."""
    s = sticks or STICKS
    v = max(-1.0, min(1.0, float(raw)))
    if pad:
        o = s["offset"].get(axis, 0.0)
        lo, hi = s["span"].get(axis, [-1.0, 1.0])
        v -= o
        v = v / (hi - o) if v > 0 else v / (o - lo) if v < 0 else 0.0
        v = max(-1.0, min(1.0, v))
    dz = s["deadzone"] / 100.0
    a = abs(v)
    if a <= dz:
        return 0.0
    t = (a - dz) / (1.0 - dz)
    k = s["curve"] / 100.0
    t = (1 - k) * t + k * t * t * t
    return t if v > 0 else -t


def read_axis(name, inp, sticks=None):
    """inp: raw page input {lx, ly, rx, ry, l2, r2, pad}; sticks -1..1 with up negative."""
    pad = inp.get("pad", True)
    if name in ("LX", "LY", "RX", "RY"):
        v = stick(name.lower(), inp.get(name.lower(), 0.0), sticks, pad)
        return -v if name[1] == "Y" else v
    if name == "L2":
        return max(0.0, min(1.0, inp.get("l2", 0.0)))
    if name == "R2":
        return max(0.0, min(1.0, inp.get("r2", 0.0)))
    if name == "R2-L2":
        return max(-1.0, min(1.0, inp.get("r2", 0.0) - inp.get("l2", 0.0)))
    return 0.0


class Mapper:
    """Keeps the smoothed value per port between ticks."""

    def __init__(self, mapping=None):
        self.mapping = mapping or default()
        self.value = {p: 0.0 for p in PORTS}  # speed %, or angle in degrees for position ports

    def set_mapping(self, mapping):
        """Ports keep their smoothed value unless their mode changed, so moving a slider
        while driving doesn't snap the steering back to centre."""
        old = self.mapping["ports"]
        self.mapping = mapping
        for p in PORTS:
            if (old.get(p) or {}).get("mode") != mapping["ports"][p]["mode"]:
                self.value[p] = 0.0

    def targets(self, inp):
        """What each port should do right now, before smoothing."""
        m = self.mapping
        sp = m["speed"]
        st = m.get("sticks")
        boost = read_axis(sp["boost"], inp, st) if sp["boost"] != "none" else 0.0
        scale = (sp["base"] + (100 - sp["base"]) * max(0.0, boost)) / 100
        d = m["drive"]
        thr = read_axis(d["throttle"], inp, st)
        steer = read_axis(d["steer"], inp, st) * d["turn"] / 100
        left, right = thr + steer, thr - steer
        n = max(1.0, abs(left), abs(right))
        left, right = left / n, right / n
        out = {}
        for p, c in m["ports"].items():
            mode = c["mode"]
            sign = -1.0 if c.get("invert") else 1.0
            if mode == "drive":
                out[p] = ("s", sign * (left if c["side"] == "left" else right) * scale * c["max"])
            elif mode == "speed":
                out[p] = ("s", sign * read_axis(c["input"], inp, st) * scale * c["max"])
            elif mode == "position":
                out[p] = ("p", sign * read_axis(c["input"], inp, st) * c["range"])
            else:
                out[p] = None
        return out

    def step(self, inp, dt, stop=False):
        """Advances one tick. inp None means no input (motors off / page gone).
        Returns {port: ("s", pct) | ("p", deg, speed_pct) | None}."""
        result = {}
        targets = self.targets(inp) if inp is not None else {}
        for p, c in self.mapping["ports"].items():
            mode = c["mode"]
            if mode == "off":
                result[p] = None
                continue
            t = targets.get(p)
            if mode == "position":
                goal = t[1] if (t and not stop) else self.value[p]  # hold the angle when stopping
                full = c["range"]
            else:
                goal = t[1] if (t and not stop) else 0.0
                full = 100.0
            if stop or inp is None:
                if mode != "position":
                    self.value[p] = 0.0  # stopping is immediate
            else:
                smooth = c.get("smooth", 0)
                if smooth > 0 and dt > 0:
                    step = full / smooth * dt
                    cur = self.value[p]
                    self.value[p] = cur + max(-step, min(step, goal - cur))
                else:
                    self.value[p] = goal
            v = self.value[p]
            if mode == "position":
                result[p] = ("p", round(v), int(c["speed"]))
            else:
                result[p] = ("s", int(round(max(-100, min(100, v)))))
        return result


def line(result):
    """{port: cmd} -> 'P A=s:40 B=p:30:60 C=- D=-' for the receiver."""
    parts = []
    for p in PORTS:
        r = result.get(p)
        if r is None:
            parts.append(f"{p}=-")
        elif r[0] == "s":
            parts.append(f"{p}=s:{r[1]}")
        else:
            parts.append(f"{p}=p:{r[1]}:{r[2]}")
    return "P " + " ".join(parts)


# ---------- persistence ----------
HERE = os.path.dirname(os.path.abspath(__file__))
SAVED = os.path.join(HERE, "mapping.json")


def load():
    try:
        with open(SAVED, encoding="utf-8") as f:
            return validate(json.load(f))
    except (OSError, ValueError):
        return default()


def save(m):
    with open(SAVED, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2)
