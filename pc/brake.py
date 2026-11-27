"""The obstacle brake: slows the robot near something in front of its range sensor, and stops it short.

It runs on the laptop, in the console's 50-a-second sending loop, after the controls mapping:
it can only take speed away, never add it, so Stop and the brick's own safety stop still win.

The brick reports the infrared or ultrasonic reading 4 times a second, and the reading is up to
a quarter of a second old by the time it's used. So the brake doesn't trust the distance as read:
it subtracts how far the robot has driven towards the obstacle since (from the wheels' measured
speed), plus a little for the command's trip back to the brick.

Only motion towards the sensor is braked. With the sensor facing ahead, the robot can still
back away and turn on the spot when it's stopped, so it never gets stuck.
"""

STOP, SLOW = 15.0, 40.0   # cm: default stop distance, and where slowing down starts
CREEP = 0.1               # less than this share of the speed is no speed: stop, don't creep
LAG = 0.15                # s: the command's trip to the brick and the motors answering
STALE = 0.8               # s: a reading older than this is too old to drive on
RISE = 2.0                # how fast speed may come back, in full speed per second
FACING = 30.0             # degrees: a sensor within this of straight ahead (or behind) counts


def settings(d):
    """Checked brake settings from the page: {"on", "stop", "slow"} in cm."""
    d = d if isinstance(d, dict) else {}
    out = {"on": bool(d.get("on", True)), "stop": STOP, "slow": SLOW}
    try:
        out["stop"] = max(5.0, min(40.0, float(d.get("stop", STOP))))
    except (TypeError, ValueError):
        pass
    try:
        out["slow"] = max(out["stop"] + 5.0, min(70.0, float(d.get("slow", SLOW))))
    except (TypeError, ValueError):
        out["slow"] = max(out["stop"] + 5.0, SLOW)
    return out


def facing(eye_angle):
    """+1 if the range sensor looks ahead, -1 if it looks back, 0 if it looks sideways."""
    a = (float(eye_angle) + 180.0) % 360.0 - 180.0
    if abs(a) <= FACING:
        return 1
    if abs(a) >= 180.0 - FACING:
        return -1
    return 0


def factor(dist, stop, slow):
    """How much of the asked-for speed is allowed at this distance: 0 at the stop distance, 1 from slow.
    The last bit is a stop too: a crawl at a few percent would still end up touching it."""
    if dist >= slow:
        return 1.0
    f = (dist - stop) / (slow - stop)
    return f if f >= CREEP else 0.0


def _sides(res, lay):
    """The drive ports' speeds, as the robot sees them: forward is positive. {port: (side, speed, sign)}."""
    out = {}
    if not lay:
        return out
    groups = (("left", lay["left"]), ("right", lay["right"])) if lay["type"] == "tank" else (("drive", lay["drive"]),)
    for side, ports in groups:
        for p, sign in ports.items():
            r = res.get(p)
            if r and r[0] == "s":
                out[p] = (side, r[1] * sign, sign)
    return out


class Brake:
    """Keeps how much speed was allowed last time, so speed comes back gradually after a stop."""

    def __init__(self):
        self.allowed = 1.0
        self.last = None
        self.state = {"state": "off", "dist": None, "allowed": 1.0}

    def apply(self, res, lay, eye, conf, robot, now):
        """res: one tick's port commands (mapping.Mapper.step). eye: the latest range reading
        {"dist", "hit", "at", "speed"} or None when no range sensor is plugged in. conf: settings().
        robot: the map's robot settings (which way the sensor faces). Returns the braked commands."""
        dt = 0.0 if self.last is None else max(0.0, min(0.2, now - self.last))
        self.last = now
        face = facing(robot.get("eyeAngle", 0))
        if not conf["on"] or not lay or eye is None or face == 0:
            self.allowed = 1.0
            why = "off" if not conf["on"] else "no layout" if not lay else "no sensor" if eye is None else "sideways"
            self.state = {"state": why, "dist": None, "allowed": 1.0}
            return res
        age = now - eye["at"]
        if age > STALE:
            dist = None
            want = 0.0  # can't see: don't drive towards whatever might be there
        else:
            # how far is it now, not when it was measured: the robot has kept driving since
            towards = max(0.0, eye.get("speed", 0.0) * face)
            dist = eye["dist"] - towards * (age + LAG) if eye["hit"] else eye["dist"]
            want = factor(dist, conf["stop"], conf["slow"]) if eye["hit"] else 1.0
        if self.allowed == 0.0 and want < 2 * CREEP:
            want = 0.0  # once stopped, stay stopped until clearly further away: no stop-start shuffle
        # less speed at once, more speed only gradually
        self.allowed = want if want < self.allowed else min(want, self.allowed + RISE * dt)
        a = self.allowed
        out = dict(res)
        sides = _sides(res, lay)
        moving = False
        if lay["type"] == "tank":
            left = [v for s, v, _ in sides.values() if s == "left"]
            right = [v for s, v, _ in sides.values() if s == "right"]
            if left and right:
                ahead = (sum(left) / len(left) + sum(right) / len(right)) / 2
                if ahead * face > 0:
                    # take away only the forward part; the turning part stays, so it can turn on the spot
                    cut = ahead * (1.0 - a)
                    moving = abs(ahead) > 0.5
                    for p, (s, v, sign) in sides.items():
                        out[p] = ("s", int(round((v - cut) * sign)))
        else:
            vals = [v for _, v, _ in sides.values()]
            if vals and sum(vals) / len(vals) * face > 0:
                moving = abs(sum(vals) / len(vals)) > 0.5
                for p, (s, v, sign) in sides.items():
                    out[p] = ("s", int(round(v * a * sign)))
        name = "blind" if dist is None else "stop" if a <= 0.0 else "slow" if a < 1.0 else "clear"
        self.state = {"state": name, "dist": None if dist is None else round(max(0.0, dist), 1),
                      "allowed": round(a, 2), "braking": moving and a < 1.0}
        return out
