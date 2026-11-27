"""Free floor from the robot camera: in each direction across the picture, how far the floor
goes before something stands on it.

Most rooms have a fairly plain floor, so the method is simple and quick. Learn what the floor
looks like from just in front of the robot (the bottom of the picture), then scan each column of
the picture upwards until it stops looking like floor. Where it stops is where something stands
on the floor; worldmap.WorldMap.surround turns that row into a distance, from the camera's height
and tilt.

"Looks like floor" compares colour (red and green as shares of the brightness) separately from
brightness, so a shadow on the floor is still floor, but a box of another colour isn't.

Weak spots: a patterned rug (the quality drops, and the brake then ignores the camera), a thing
the same colour as the floor, and white skirting on a white floor. The infrared sensor still
covers straight ahead.

Standard library only: the picture arrives as a small list of (r, g, b) pixels. Pillow, which
recognition already needs, is only used to shrink a JPEG to that size (from_jpeg).
"""
import io

W, H = 64, 48          # the picture is shrunk to this before scanning: 4:3, like the camera's
COLS = 32              # directions across the picture
REF_ROWS = 4           # rows at the bottom the floor's look is learned from
CHROMA = 0.045         # colour difference still counted as floor (shares of brightness)
DARKER, LIGHTER = 0.5, 1.7  # brightness range still counted as floor: shadows and bright patches
RUN = 2                # rows in a row that aren't floor: the floor has ended
LEARN = 0.08           # how quickly the floor's look follows a slow change (lighting, a new room)
SAME = 0.6             # share of the bottom rows that must match the learned floor to learn from them


class Picture:
    """A small picture: w x h (r, g, b) pixels, row by row from the top."""

    def __init__(self, w, h, pixels):
        self.w, self.h, self.pixels = w, h, pixels


def from_jpeg(jpeg, w=W, h=H):
    """A JPEG shrunk to w x h. Needs Pillow; raises OSError or ValueError for a broken picture."""
    from PIL import Image
    im = Image.open(io.BytesIO(jpeg))
    im.draft("RGB", (w * 2, h * 2))  # decode at a fraction of the size: much quicker
    im = im.convert("RGB").resize((w, h), getattr(Image, "Resampling", Image).BILINEAR)
    data = im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata()
    return Picture(w, h, list(data))


def look(p):
    """A pixel as (red share, green share, brightness): colour apart from how bright it is."""
    r, g, b = p
    s = r + g + b + 3
    return r / s, g / s, s


def _median(v):
    v = sorted(v)
    return v[len(v) // 2]


def is_floor(p, ref):
    r, g, s = look(p)
    return abs(r - ref[0]) + abs(g - ref[1]) <= CHROMA and DARKER * ref[2] <= s <= LIGHTER * ref[2]


class Scanner:
    """Remembers the floor's look between pictures, so that a box right in front of the robot,
    filling the bottom of the picture, isn't taken for the floor."""

    def __init__(self):
        self.ref = None

    def reset(self):
        self.ref = None

    def scan(self, pic, cols=COLS):
        """{"cols": [where the floor ends, from 0 (top) to 1 (bottom), or None when it goes on to
        the top of the picture], "quality": 0..1, how plain the floor in front looks}."""
        w, h, px = pic.w, pic.h, pic.pixels
        patch = [px[y * w + x] for y in range(h - REF_ROWS, h) for x in range(w // 4, w - w // 4)]
        looks = [look(p) for p in patch]
        here = (_median([a for a, _, _ in looks]), _median([b for _, b, _ in looks]), _median([c for _, _, c in looks]))
        if self.ref is None:
            self.ref = here
        same = sum(1 for p in patch if is_floor(p, self.ref)) / len(patch)
        if same >= SAME:
            # the floor in front matches what was learned: follow slow changes, like the lighting
            self.ref = tuple(a + (b - a) * LEARN for a, b in zip(self.ref, here))
        # how plain the floor in front is: on a patterned rug many of its own pixels don't match it
        quality = sum(1 for p in patch if is_floor(p, here)) / len(patch)
        ref = self.ref
        floor = [[is_floor(px[y * w + x], ref) for x in range(w)] for y in range(h)]
        band = w / cols
        ends = []
        for c in range(cols):
            x0, x1 = int(c * band), max(int(c * band) + 1, int((c + 1) * band))
            run, end = 0, None
            for y in range(h - 1, -1, -1):
                row = floor[y][x0:x1]
                if sum(row) * 2 >= len(row):
                    run = 0
                    continue
                run += 1
                if run >= RUN:
                    end = (y + RUN) / h  # the bottom edge of the first row that isn't floor
                    break
            ends.append(end)
        # one odd column is usually noise: take the middle of each column and its neighbours
        top = lambda e: -1.0 if e is None else e  # noqa: E731
        smooth = []
        for c in range(cols):
            near = sorted((top(ends[k]) for k in range(max(0, c - 1), min(cols, c + 2))))
            m = near[len(near) // 2] if len(near) == 3 else max(near)
            smooth.append(None if m < 0 else round(m, 3))
        return {"cols": smooth, "quality": round(quality, 2)}
