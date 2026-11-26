"""Object recognition on the robot camera's video, run on the laptop.

This is optional, and the one part of PowerShock that uses packages outside the standard library:
numpy, onnxruntime and Pillow (pc/requirements-vision.txt), plus the YOLOX-nano model file
(python pc/tools/get_model.py). Without them the console works as before and the page says what's
missing; the imports happen only when recognition starts.

Recognition runs only while the page keeps asking for it, so it costs nothing otherwise. Frames
come from the Pi through camera.Camera.frames(); nothing leaves the laptop.
"""
import hashlib
import importlib.util
import io
import os
import threading
import time

import camera

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "models", "yolox_nano.onnx")
# YOLOX-nano by Megvii, Apache-2.0: https://github.com/Megvii-BaseDetection/YOLOX
MODEL_URL = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx"
MODEL_SHA256 = "c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d"
MODEL_SIZE = 3659407
PACKAGES = (("numpy", "numpy"), ("onnxruntime", "onnxruntime"), ("PIL", "pillow"))  # (import name, pip name)
SETUP = "python -m pip install -r pc/requirements-vision.txt, then python pc/tools/get_model.py (see docs/VISION.md)"

MIN_SCORE = 0.4     # how sure the model must be before a thing is shown
IOU = 0.45          # boxes overlapping more than this are the same thing
MAX_ITEMS = 25
MAX_RATE = 10       # recognitions a second at most, so the laptop stays responsive
KEEP_ALIVE = 3.0    # seconds recognition keeps going after the page last asked
THREADS = 2         # CPU threads for the model; the console's 50 Hz sender needs the rest
RETRY = 2.0         # seconds before reading the camera again after it stopped
FAIL_WAIT = 5.0     # seconds before trying again after the model failed, so its error stays readable

# The 80 kinds of thing the model knows (the COCO set), in its order, in plain words.
LABELS = (
    "person", "bicycle", "car", "motorbike", "aeroplane", "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "doughnut", "cake", "chair", "sofa",
    "plant", "bed", "table", "toilet", "TV", "laptop", "mouse", "remote", "keyboard", "phone",
    "microwave", "oven", "toaster", "sink", "fridge", "book", "clock", "vase", "scissors", "teddy bear",
    "hair dryer", "toothbrush",
)


class VisionError(Exception):
    pass


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def missing(model=MODEL):
    """What isn't here yet: pip package names, and "model" for the model file."""
    out = [pip for mod, pip in PACKAGES if importlib.util.find_spec(mod) is None]
    if not os.path.isfile(model):
        out.append("model")
    return out


def make_grids(size, strides=(8, 16, 32)):
    """Each output row's grid cell and stride: YOLOX predicts boxes relative to them."""
    import numpy as np
    grids, steps = [], []
    for s in strides:
        n = size // s
        xv, yv = np.meshgrid(np.arange(n), np.arange(n))
        grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
        steps.append(np.full((n * n, 1), s))
    return np.concatenate(grids).astype(np.float32), np.concatenate(steps).astype(np.float32)


def nms(boxes, scores, iou=IOU):
    """Indexes of the boxes to keep, best first, dropping any that mostly cover a better one."""
    import numpy as np
    x0, y0, x1, y1 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    area = (x1 - x0).clip(0) * (y1 - y0).clip(0)
    order, keep = scores.argsort()[::-1], []
    while order.size:
        i, rest = order[0], order[1:]
        keep.append(int(i))
        w = (np.minimum(x1[i], x1[rest]) - np.maximum(x0[i], x0[rest])).clip(0)
        h = (np.minimum(y1[i], y1[rest]) - np.maximum(y0[i], y0[rest])).clip(0)
        inter = w * h
        order = rest[inter / (area[i] + area[rest] - inter + 1e-9) <= iou]
    return keep


def decode(out, grids, strides, ratio, w, h, min_score=MIN_SCORE, iou=IOU, limit=MAX_ITEMS):
    """The model's raw rows (cx, cy, w, h, objectness, 80 class scores) as things found:
    [{"label", "score", "box": [x0, y0, x1, y1] as fractions of the picture}], best first."""
    import numpy as np
    scores = out[:, 4:5] * out[:, 5:]
    cls = scores.argmax(1)
    best = scores[np.arange(len(cls)), cls]
    keep = best >= min_score
    if not keep.any():
        return []
    o, g, s, cls, best = out[keep], grids[keep], strides[keep], cls[keep], best[keep]
    xy = (o[:, :2] + g) * s
    wh = np.exp(np.minimum(o[:, 2:4], 10.0)) * s
    boxes = np.concatenate([xy - wh / 2, xy + wh / 2], 1) / ratio
    boxes[:, 0::2] = boxes[:, 0::2].clip(0, w)
    boxes[:, 1::2] = boxes[:, 1::2].clip(0, h)
    # per kind of thing: a cup in front of a person is two things, not one
    shifted = boxes + (cls.astype(np.float32) * (max(w, h) + 1))[:, None]
    items = []
    for i in nms(shifted, best, iou)[:limit]:
        x0, y0, x1, y1 = boxes[i]
        if x1 - x0 < 1 or y1 - y0 < 1:
            continue
        items.append({"label": LABELS[int(cls[i])], "score": round(float(best[i]), 2),
                      "box": [round(float(x0) / w, 4), round(float(y0) / h, 4),
                              round(float(x1) / w, 4), round(float(y1) / h, 4)]})
    return items


class Detector:
    """The model, loaded once. Call it with a JPEG; it returns (things found, (width, height))."""

    def __init__(self, path=MODEL, sha256=MODEL_SHA256, threads=THREADS):
        if not os.path.isfile(path):
            raise VisionError("The model file isn't there yet. Run python pc/tools/get_model.py.")
        if sha256 and file_sha256(path) != sha256:
            raise VisionError("The model file isn't the one PowerShock expects. Run python pc/tools/get_model.py again.")
        try:
            import numpy as np
            import onnxruntime as ort
            from PIL import Image
        except ImportError as e:
            raise VisionError(f"A package is missing ({e.name}). Run {SETUP}.") from None
        self.np, self.Image = np, Image
        self.resample = getattr(Image, "Resampling", Image).BILINEAR
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])
        inp = self.session.get_inputs()[0]
        self.input, self.size = inp.name, int(inp.shape[2])
        self.grids, self.strides = make_grids(self.size)

    def prepare(self, jpeg):
        """The picture as the model wants it: fitted into a square from the top-left, grey padding,
        BGR channels first, 0-255. Returns (tensor, ratio, width, height, original size)."""
        np, S = self.np, self.size
        im = self.Image.open(io.BytesIO(jpeg))
        full = im.size
        im.draft("RGB", (S, S))  # big frames decode faster at a smaller scale
        im = im.convert("RGB")
        w, h = im.size
        r = min(S / w, S / h)
        nw, nh = max(1, int(w * r)), max(1, int(h * r))
        if (nw, nh) != (w, h):
            im = im.resize((nw, nh), self.resample)
        canvas = np.full((S, S, 3), 114, np.uint8)
        canvas[:nh, :nw] = np.asarray(im)
        x = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32)
        return x, r, w, h, full

    def __call__(self, jpeg, min_score=MIN_SCORE):
        x, r, w, h, full = self.prepare(jpeg)
        out = self.session.run(None, {self.input: x})[0][0]
        return decode(out, self.grids, self.strides, r, w, h, min_score), full


class Vision:
    """Recognition for the console: started by the page's polls, stopped when they stop."""

    def __init__(self, cam, model=MODEL, sha256=MODEL_SHA256):
        self.cam, self.model, self.sha256 = cam, model, sha256
        self.lock = threading.Lock()
        self.new_frame = threading.Condition(self.lock)
        self.detector = None
        self.worker = None
        self.until = 0.0
        self.frame, self.seq = None, 0
        self.result, self.error = None, None
        self.times = []
        self.failed_at = -1e9

    def status(self):
        miss = missing(self.model)
        with self.lock:
            running = self.worker is not None
        return {"available": not miss, "missing": miss, "setup": SETUP if miss else None,
                "running": running, "labels": len(LABELS)}

    def poll(self, on):
        """The page asks for recognition (on) or says it's done (off). Returns the latest result."""
        if on:
            miss = missing(self.model)
            if miss:
                return {"ok": False, "on": False, "missing": miss,
                        "error": "Object recognition needs a one-time setup on this laptop.", "setup": SETUP}
        now = time.monotonic()
        with self.lock:
            self.until = now + KEEP_ALIVE if on else 0.0
            if not on:
                self.new_frame.notify_all()
                return {"ok": True, "on": False}
            if self.worker is None and now - self.failed_at >= FAIL_WAIT:
                self.error, self.result, self.times = None, None, []
                self.worker = threading.Thread(target=self._work, name="vision", daemon=True)
                self.worker.start()
            r = dict(self.result or {})
            recent = [t for t in self.times if now - t < 2.0]
            r.update({"ok": True, "on": True, "error": self.error, "fps": round(len(recent) / 2.0, 1),
                      "age": round(now - r["at"], 2) if "at" in r else None})
            r.pop("at", None)
            return r

    def _wanted(self):
        with self.lock:
            if time.monotonic() <= self.until:
                return True
            self.worker = None  # under the lock, so the next poll starts a fresh worker
            return False

    def _read(self, stop):
        """Keeps only the newest frame: recognition is slower than the video and must not fall behind."""
        try:
            for jpeg in self.cam.frames(stop):
                with self.new_frame:
                    self.frame, self.seq = jpeg, self.seq + 1
                    self.new_frame.notify_all()
            if not stop.is_set():
                with self.lock:
                    self.error = "The camera stopped sending video."
        except camera.CameraError as e:
            with self.lock:
                self.error = str(e)

    def _work(self):
        stop, reader, next_try, seen = threading.Event(), None, 0.0, 0
        try:
            if self.detector is None:
                self.detector = Detector(self.model, self.sha256)
            while self._wanted():
                if reader is None or not reader.is_alive():
                    if time.monotonic() >= next_try:
                        stop = threading.Event()
                        reader = threading.Thread(target=self._read, args=(stop,), name="vision-camera", daemon=True)
                        reader.start()
                        next_try = time.monotonic() + RETRY
                with self.new_frame:
                    self.new_frame.wait_for(lambda: self.seq != seen or time.monotonic() > self.until, timeout=0.5)
                    if self.seq == seen:
                        continue
                    jpeg, seen = self.frame, self.seq
                t0 = time.monotonic()
                try:
                    items, size = self.detector(jpeg)
                except (OSError, ValueError, SyntaxError):
                    continue  # a frame Pillow can't read; the next one will do
                t1 = time.monotonic()
                with self.lock:
                    self.result = {"items": items, "size": list(size), "ms": round((t1 - t0) * 1000), "at": t1}
                    self.times = [t for t in self.times if t1 - t < 2.0] + [t1]
                    self.error = None
                rest = 1.0 / MAX_RATE - (time.monotonic() - t0)
                if rest > 0:
                    time.sleep(rest)
        except Exception as e:  # the model wouldn't load or run: say so, and let the next poll try again
            with self.lock:
                self.error = str(e) if isinstance(e, VisionError) else f"Object recognition stopped: {e}"
                self.worker = None
                self.failed_at = time.monotonic()
        finally:
            stop.set()
