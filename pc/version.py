"""PowerShock's version, read from the VERSION file at the top of the repository.

One number for the whole app: the console, the brick programs (stamped in by build.ps1)
and CHANGELOG.md all use it. See "Versioning" in CHANGELOG.md.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?$")


def read(path=os.path.join(ROOT, "VERSION")):
    try:
        with open(path, encoding="utf-8") as f:
            v = f.read().strip()
    except OSError:
        return "0.0.0-unknown"
    return v if SEMVER.match(v) else "0.0.0-invalid"


def parse(v):
    """'0.7.0' -> (0, 7, 0); a pre-release like '0.8.0-beta' sorts before '0.8.0'. None if not a version."""
    m = SEMVER.match(v or "")
    if not m:
        return None
    return int(m[1]), int(m[2]), int(m[3]), (0, m[4]) if m[4] else (1, "")


__version__ = read()
