"""The obstacle brake: slows the robot near something in front of its range sensor, and stops it short.

It runs on the laptop, in the console's 50-a-second sending loop, after the controls mapping:
it can only take speed away, never add it, so Stop and the brick's own safety stop still win.

The brick reports the infrared or ultrasonic reading 4 times a second, and the reading is up to
a quarter of a second old by the time it's used. So the brake doesn't trust the distance as read:
it subtracts how far the robot has driven towards the obstacle since (from the wheels' measured
speed), plus a little for the command's trip back to the brick.

Only motion towards the sensor is braked. With the sensor facing ahead, the robot can still
back away and turn on the spot when it's stopped, so it never gets stuck.

The camera, when it watches the floor (pc/floor.py), adds the nearest thing in the robot's way
across its whole width, not just along the infrared sensor's narrow line. The nearer of the two
counts. With a person or a pet close ahead (from object recognition), the brake keeps twice the
distance and allows half the speed.
"""

STOP, SLOW = 15.0, 40.0   # cm: default stop distance, and where slowing down starts
CREEP = 0.1               # less than this share of the speed is no speed: stop, don't creep
LAG = 0.15                # s: the command's trip to the brick and the motors answering
STALE = 0.8               # s: a reading older than this is too old to drive on
RISE = 2.0                # how fast speed may come back, in full speed per second
FACING = 30.0             # degrees: a sensor within this of straight ahead (or behind) counts
CAREFUL_SPEED = 0.5       # most of the speed allowed near a person or pet
LOG_KEEP = 12             # decisions kept for the page
SETTLE = 0.3              # s a decision must hold before it's logged, so the edge of the slow zone doesn't flicker


def settings(d):
    """Checked brake settings from the page: {"on", "stop", "slow" (cm), "camera" (use it too)}."""
    d = d if isinstance(d, dict) else {}
    out = {"on": bool(d.get("on", True)), "stop": STOP, "slow": SLOW, "camera": bool(d.get("camera", True))}
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


def forward(res, lay):
    """How fast the commands drive forward, in percent (negative: backwards), or None with no layout."""
    sides = _sides(res, lay)
    if not lay:
        return None
    mean = lambda v: sum(v) / len(v) if v else 0.0  # noqa: E731
    if lay["type"] == "tank":
        return (mean([v for s, v, _ in sides.values() if s == "left"]) + mean([v for s, v, _ in sides.values() if s == "right"])) / 2
    return mean([v for _, v, _ in sides.values()])


class Brake:
    """Keeps how much speed was allowed last time, so speed comes back gradually after a stop."""

    def __init__(self):
        self.allowed = 1.0
        self.last = None
        self.state = {"state": "off", "dist": None, "allowed": 1.0}
        self.log = []          # decisions, newest last: {"at", "what", "dist", "src", "careful"}
        self.logged = None     # the decision last logged
        self.pending = None    # (decision, since) not held long enough yet

    def _note(self, what, now):
        """Logs what the brake decided, when it changes and holds: clear, slow, stop, blind, careful, off..."""
        st = self.state
        key = (what, st.get("careful"))
        if key == self.logged:
            self.pending = None
            return
        if what == "clear" and not st.get("careful") and (self.logged is None or self.logged[0] not in ("slow", "stop", "blind")
                                                          and not self.logged[1]):
            self.logged = key  # only coming back from braking is worth saying
            return
        if self.pending is None or self.pending[0] != key:
            self.pending = (key, now)
        if what in ("stop", "blind") or now - self.pending[1] >= SETTLE:
            self.log.append({"at": now, "what": what, "dist": st.get("dist"), "src": st.get("src"),
                             "careful": st.get("careful")})
            del self.log[:-LOG_KEEP]
            self.logged, self.pending = key, None

    def decisions(self, now):
        """The logged decisions for the page, newest first, with how long ago each was."""
        return [dict({k: v for k, v in e.items() if k != "at"}, ago=round(now - e["at"], 1)) for e in reversed(self.log)]

    def apply(self, res, lay, eye, conf, robot, now, cam=None):
        """res: one tick's port commands (mapping.Mapper.step). eye: the latest range reading
        {"dist", "hit", "at", "speed"} or None when no range sensor is plugged in. conf: settings().
        robot: the map's robot settings (which way the sensor faces). cam: the camera's view
        (worldmap.WorldMap.camera_now) or None. Returns the braked commands."""
        dt = 0.0 if self.last is None else max(0.0, min(0.2, now - self.last))
        self.last = now
        face = facing(robot.get("eyeAngle", 0))
        ir = eye if eye is not None and face != 0 else None
        # the camera looks ahead, so it only helps when the range sensor does too, or isn't there
        cam = cam if conf.get("camera", True) and face != -1 else None
        if ir is None and cam is not None:
            face = 1
        if not conf["on"] or not lay or (ir is None and cam is None):
            self.allowed = 1.0
            why = ("off" if not conf["on"] else "no layout" if not lay
                   else "no sensor" if eye is None else "sideways")
            fwd = forward(res, lay)
            self.state = {"state": why, "dist": None, "allowed": 1.0,
                          "asked": None if fwd is None else round(fwd), "given": None if fwd is None else round(fwd)}
            self._note(why, now)
            return res
        stop, slow, top = conf["stop"], conf["slow"], 1.0
        careful = cam.get("careful") if cam else None
        if careful:
            stop = min(60.0, stop * 2)
            slow, top = min(150.0, max(slow * 2, stop + 10)), CAREFUL_SPEED
        speed = (ir or cam).get("speed", 0.0)
        towards = max(0.0, speed * face)
        near, src, blind = [], None, False
        if ir is not None:
            age = now - ir["at"]
            if age > STALE:
                blind = True  # can't see: don't drive towards whatever might be there
            elif ir["hit"]:
                # how far is it now, not when it was measured: the robot has kept driving since
                near.append((ir["dist"] - towards * (age + LAG), {"us": "ultrasonic"}.get(ir.get("kind"), "infrared")))
        if cam is not None:
            age = now - cam["at"]
            if age > STALE and ir is None:
                blind = True  # the camera was all it had, and it stopped
            elif age <= STALE and cam.get("good") and cam.get("dist") is not None:
                # measured from where the range sensor is, like its own readings
                shift = (robot.get("camAhead", 0) - robot.get("eyeAhead", 0)) / 10 if ir is not None else 0.0
                near.append((cam["dist"] + shift - towards * (age + LAG), "camera"))
        dist = None
        if blind:
            want = 0.0
        else:
            want = top
            if near:
                dist, src = min(near)
                want = min(top, factor(dist, stop, slow))
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
        name = "blind" if blind else "stop" if a <= 0.0 else "slow" if a < 1.0 else "clear"
        self.state = {"state": name, "dist": None if dist is None else round(max(0.0, dist), 1),
                      "allowed": round(a, 2), "braking": moving and a < 1.0, "src": src,
                      "careful": careful, "camera": cam is not None and bool(cam.get("good")),
                      "stop": stop, "slow": slow,
                      "asked": round(forward(res, lay)), "given": round(forward(out, lay))}
        # what it decided: only a change to the robot's driving counts, not what it merely sees
        self._note(name if moving and a < 1.0 or name == "blind" else "clear", now)
        return out
