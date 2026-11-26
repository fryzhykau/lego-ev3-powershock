"""Controller -> motor mixing. Keep in sync with ev3/src/powershock/Mixer.java.

Sticks in [-1, 1] (up is negative Y), trigger in [0, 1].
Returns (left, right, aux) percentages in [-100, 100].
"""

import math

DEADZONE = 0.08
BASE_SCALE = 0.5  # speed without turbo; R2 fully pressed gives 100%


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def deadzone(v):
    v = clamp(v, -1.0, 1.0)
    a = abs(v)
    if a < DEADZONE:
        return 0.0
    return (1.0 if v > 0 else -1.0) * (a - DEADZONE) / (1.0 - DEADZONE)


def pct(v):
    # Java's Math.round rounds halves up; match it so both sides agree.
    return int(math.floor(clamp(v, -1.0, 1.0) * 100.0 + 0.5))


def mix(lx, ly, ry, r2, stop=False):
    if stop:
        return 0, 0, 0
    throttle = -deadzone(ly)
    turn = deadzone(lx)
    aux = -deadzone(ry)

    left = throttle + turn
    right = throttle - turn
    m = max(abs(left), abs(right))
    if m > 1.0:
        left /= m
        right /= m

    scale = BASE_SCALE + (1.0 - BASE_SCALE) * clamp(r2, 0.0, 1.0)
    return pct(left * scale), pct(right * scale), pct(aux * scale)
