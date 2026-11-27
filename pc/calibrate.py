"""Car calibration, repeatable at any time: what the car can really do, measured on the car.

- Steering limits: the steering motor turns slowly each way until it meets the end stop. Centre
  is set halfway between, and the steering's "Turns up to" is kept a few degrees inside the stops.
- Turning circle: the car drives slowly at full lock, and the owner says when it's back where it
  started. The distance the wheels measured is the circle; with the axle spacing, that gives the
  front wheels' real angle at full lock, and so the steering ratio the map needs.
- Top speed against the battery: learned by itself whenever the car is driven straight at full
  power. A motor's top speed falls as the battery drains, roughly in proportion to its voltage.

Results are kept in pc/calibration.json (git-ignored), with when each was measured.
"""
import json
import math
import os
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "calibration.json")

STEER_SPEED = 15      # % of top speed while feeling for an end stop: gentle on the steering
STILL_DEG = 2         # turning less than this ...
STILL_S = 0.6         # ... for this long: it has reached the stop
SIDE_LIMIT_S = 6.0    # s: give up on one side after this (no end stop?)
MARGIN = 4            # degrees kept clear of each end stop
TURN_SPEED = 25       # % drive speed while measuring the turning circle
TURN_STEER_FIRST = 0.8  # s: the wheels turn to full lock before the car moves
KEEP = 0.6            # s: the page must keep asking, or the turning drive stops
TOP_POWER = 95        # % command that counts as full power
TOP_STRAIGHT = 0.1    # share of full lock that still counts as straight
TOP_HOLD = 1.0        # s at full power before the speed counts (it has to get up to speed)
TOP_EVERY = 0.5       # s between samples
TOP_KEEP = 60         # samples kept
SAVE_EVERY = 10.0     # s: at most this often to disk while learning


def fit_top(samples):
    """cm/s per volt, through zero (top speed is close to proportional to the voltage), or None."""
    vv = sum(v * v for v, _ in samples)
    return sum(v * s for v, s in samples) / vv if samples and vv > 0 else None


def wheel_angle(across, base):
    """The front wheels' angle (degrees) that drives the rear axle round a circle this wide (cm),
    for a car with this axle spacing (cm): a bicycle model."""
    return math.degrees(math.atan(base / (across / 2)))


class Calibration:
    def __init__(self, config=CONFIG):
        self.config = config
        self.lock = threading.Lock()
        self.data = self._load()
        self.job = None            # what's running: {"what", "state", "note", ...}
        self.abort = threading.Event()
        self.hold_since = None     # top speed: full power and straight since
        self.last_sample = 0.0
        self.saved_at = 0.0
        self.dirty = False

    def _load(self):
        try:
            with open(self.config, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        d = d if isinstance(d, dict) else {}
        speed = d.get("speed") if isinstance(d.get("speed"), dict) else {}
        samples = [(float(v), float(s)) for v, s in (speed.get("samples") or [])
                   if isinstance(v, (int, float)) and isinstance(s, (int, float))][-TOP_KEEP:]
        turn = d.get("turn") if isinstance(d.get("turn"), dict) else {}
        return {"steer": d.get("steer") if isinstance(d.get("steer"), dict) else None,
                "turn": {k: v for k, v in turn.items() if k in ("left", "right") and isinstance(v, dict)},
                "speed": {"samples": samples}}

    def save(self):
        with self.lock:
            d = json.loads(json.dumps(self.data))
            self.dirty, self.saved_at = False, time.monotonic()
        try:
            with open(self.config, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2)
        except OSError:
            pass

    def forget(self, what):
        with self.lock:
            if what == "steer":
                self.data["steer"] = None
            elif what == "turn":
                self.data["turn"] = {}
            elif what == "speed":
                self.data["speed"] = {"samples": []}
            else:
                return False
        self.save()
        return True

    def snapshot(self, volts=None):
        with self.lock:
            d = json.loads(json.dumps(self.data))
            job = dict(self.job) if self.job else None
        samples = d["speed"]["samples"]
        k = fit_top(samples)
        d["speed"] = {"samples": len(samples), "perVolt": None if k is None else round(k, 2),
                      "now": None if k is None or not volts else round(k * volts, 1), "volts": volts,
                      "from": [round(min(v for v, _ in samples), 2), round(max(v for v, _ in samples), 2)] if samples else None}
        d["job"] = job
        return d

    # ---------- top speed, learned while driving ----------
    def observe(self, power, straight, speed, volts, now):
        """Called 50 times a second with the command's forward power (%), whether the car is
        going straight, its measured speed (cm/s) and the battery voltage."""
        if volts is None or power is None or abs(power) < TOP_POWER or not straight or abs(speed) < 1:
            self.hold_since = None
            return
        if self.hold_since is None:
            self.hold_since = now
            return
        if now - self.hold_since < TOP_HOLD or now - self.last_sample < TOP_EVERY:
            return
        self.last_sample = now
        with self.lock:
            s = self.data["speed"]["samples"]
            s.append((round(volts, 2), round(abs(speed), 1)))
            del s[:-TOP_KEEP]
            self.dirty = True
            due = now - self.saved_at > SAVE_EVERY
        if due:
            self.save()

    # ---------- steering limits ----------
    def set_job(self, **kw):
        with self.lock:
            self.job = dict(kw) if kw else None

    def find_steer(self, port, send, tacho, sleep=time.sleep, clock=time.monotonic):
        """Feels for both end stops of the steering motor on `port`. send(line) sends a motor test
        line; tacho() is its latest angle (or None). Returns the result, or raises RuntimeError."""
        self.abort.clear()
        ends = []
        for direction, name in ((-1, "left"), (1, "right")):
            self.set_job(what="steer", state="running", note=f"Turning the steering {name} to its end stop…")
            ends.append(self._feel(port, direction, send, tacho, sleep, clock))
            if self.abort.is_set():
                send(f"M {port} stop 0 50")
                raise RuntimeError("Stopped.")
        lo, hi = min(ends), max(ends)
        span = hi - lo
        if span < 10:
            raise RuntimeError("The steering hardly moved. Is a motor on that port, and free to turn?")
        centre = (lo + hi) / 2
        self.set_job(what="steer", state="running", note="Turning back to the centre…")
        now = tacho()
        send(f"M {port} rotate {int(round(centre - now))} 30")
        t0 = clock()
        while clock() - t0 < 4 and abs((tacho() or 0) - centre) > 3 and not self.abort.is_set():
            sleep(0.1)
        sleep(0.3)
        send(f"M {port} zero 0 50")  # this is now 0°: straight ahead
        each = span / 2
        result = {"port": port, "eachWay": round(each, 1), "range": max(5, int(each - MARGIN)), "at": time.time()}
        with self.lock:
            self.data["steer"] = result
        self.save()
        return result

    def _feel(self, port, direction, send, tacho, sleep, clock):
        start = tacho()
        if start is None:
            raise RuntimeError("No reading from the steering motor. Is the brick connected?")
        last, moved_at, t0 = start, clock(), clock()
        while clock() - t0 < SIDE_LIMIT_S and not self.abort.is_set():
            send(f"M {port} run {direction * STEER_SPEED} 50")  # a held run stops by itself if this stops
            sleep(0.15)
            now = tacho()
            if now is None:
                break
            if abs(now - last) >= STILL_DEG:
                last, moved_at = now, clock()
            elif clock() - moved_at >= STILL_S:
                break
        send(f"M {port} stop 0 50")
        sleep(0.3)
        return tacho() if tacho() is not None else last

    # ---------- turning circle ----------
    def turn_result(self, side, travelled, lock_deg, base_cm):
        """The circle driven at full lock: travelled (cm) is the distance the wheels measured, lock_deg
        the steering motor's angle at full lock. Stores and returns the result."""
        if travelled < 30:
            raise RuntimeError("That was too short to measure: drive a whole circle, then press Back where it started.")
        across = travelled / math.pi
        angle = wheel_angle(across, base_cm)
        result = {"across": round(across, 1), "wheel": round(angle, 1), "lock": round(lock_deg, 1),
                  "ratio": round(angle / lock_deg, 3) if lock_deg else None, "at": time.time()}
        with self.lock:
            self.data["turn"][side] = result
        self.save()
        return result

    def steer_ratio(self):
        """The steering ratio from the turning circles measured (both sides averaged), or None."""
        with self.lock:
            rs = [t["ratio"] for t in self.data["turn"].values() if t.get("ratio")]
        return round(sum(rs) / len(rs), 3) if rs else None
