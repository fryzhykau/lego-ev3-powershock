"""Object recognition on the robot camera's video, run on the laptop.

This is optional, and the one part of PowerShock that uses packages outside the standard library:
numpy, onnxruntime and Pillow (pc/requirements-vision.txt), plus the YOLOX-nano model file
(python pc/tools/get_model.py). Without them the console works as before and the page says what's
missing; the imports happen only when recognition starts.

Recognition runs only while the page keeps asking for it, so it costs nothing otherwise. Frames
come from the Pi through camera.Camera.frames(); nothing leaves the laptop.

Four sizes of the same model can be chosen (MODELS): bigger ones find smaller and farther things
and guess wrong less often, but take longer. With onnxruntime-directml instead of onnxruntime,
they run on the laptop's graphics chip (any DirectX 12 one): fast enough for the biggest. The
choice is kept in pc/vision.json, which git ignores.

The same frames also feed the free-floor scan (pc/floor.py), which needs only Pillow. It runs
while the page asks for it (watch_floor), with or without recognition. In Practice, the floor
scan watches the practice room instead, through a pretend camera (Vision's practice argument).
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import threading
import time

import camera
import floor

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(HERE, "vision.json")
RELEASE = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/"
# YOLOX by Megvii, Apache-2.0: https://github.com/Megvii-BaseDetection/YOLOX
# "accuracy" is the COCO score (mAP) the YOLOX authors give; "input" the picture size it looks at.
MODELS = {
    "nano": {"label": "Fast", "file": "yolox_nano.onnx", "size": 3659407, "input": 416, "accuracy": 25.8,
             "sha256": "c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d"},
    "tiny": {"label": "Balanced", "file": "yolox_tiny.onnx", "size": 20219662, "input": 416, "accuracy": 32.8,
             "sha256": "427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7"},
    "s": {"label": "Better", "file": "yolox_s.onnx", "size": 35858002, "input": 640, "accuracy": 40.5,
          "sha256": "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063"},
    "m": {"label": "Best", "file": "yolox_m.onnx", "size": 101259744, "input": 640, "accuracy": 46.9,
          "sha256": "21ff6cfdeb53b013bac2249599e55f00bff3cfdfdab37ed7a4620818c1d15b3f"},
}
CHIPS = ("auto", "gpu", "cpu")  # auto: the graphics chip when there's one to use, else the processor


def model_path(name):
    return os.path.join(HERE, "models", MODELS[name]["file"])


def model_url(name):
    return RELEASE + MODELS[name]["file"]


MODEL = model_path("nano")  # the default, and the one the tests use
MODEL_URL = model_url("nano")
MODEL_SHA256 = MODELS["nano"]["sha256"]
MODEL_SIZE = MODELS["nano"]["size"]
PACKAGES = (("numpy", "numpy"), ("onnxruntime", "onnxruntime"), ("PIL", "pillow"))  # (import name, pip name)
SETUP = "python -m pip install -r pc/requirements-vision.txt, then python pc/tools/get_model.py (see docs/VISION.md)"
GPU_TRIES = 3       # graphics chips tried, by DirectML's numbering (0 is often the one built into the processor)

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


def load_settings(path=SETTINGS):
    """{"model", "chip"}: what the owner chose, checked; nano on "auto" when nothing is saved."""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    return {"model": d.get("model") if d.get("model") in MODELS else "nano",
            "chip": d.get("chip") if d.get("chip") in CHIPS else "auto"}


def gpu_available():
    """Whether onnxruntime can use a graphics chip here (the onnxruntime-directml package)."""
    try:
        import onnxruntime as ort
    except ImportError:
        return False
    return "DmlExecutionProvider" in ort.get_available_providers()


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
    """The model, loaded once. Call it with a JPEG; it returns (things found, (width, height)).
    chip "gpu" (or "auto" with DirectML there) times each graphics chip and keeps the fastest."""

    def __init__(self, path=MODEL, sha256=MODEL_SHA256, threads=THREADS, chip="cpu"):
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
        self.session, self.where = None, "processor"
        if chip == "gpu" or (chip == "auto" and gpu_available()):
            self.session, self.where = self._fastest_gpu(ort, path)
        if self.session is None:
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = threads
            opts.inter_op_num_threads = 1
            opts.log_severity_level = 3
            self.session = ort.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])
            self.where = "processor"
        inp = self.session.get_inputs()[0]
        self.input, self.size = inp.name, int(inp.shape[2])
        self.grids, self.strides = make_grids(self.size)

    @staticmethod
    def _fastest_gpu(ort, path):
        """(session, "graphics chip N") on the quickest graphics chip, or (None, None) if none works.
        DirectML doesn't name its chips, so each is timed on a blank picture."""
        import numpy as np
        if "DmlExecutionProvider" not in ort.get_available_providers():
            return None, None
        best = (None, None, 1e9)
        for dev in range(GPU_TRIES):
            try:
                opts = ort.SessionOptions()
                opts.log_severity_level = 3
                opts.enable_mem_pattern = False  # DirectML needs these two
                opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
                # a chip number that doesn't exist makes onnxruntime print an error block and fall
                # back to the processor: keep that out of the console's window, and stop there
                with contextlib.redirect_stdout(io.StringIO()):
                    s = ort.InferenceSession(path, sess_options=opts, providers=[("DmlExecutionProvider", {"device_id": dev})])
                if s.get_providers()[0] != "DmlExecutionProvider":
                    break
                inp = s.get_inputs()[0]
                n = int(inp.shape[2])
                x = np.zeros((1, 3, n, n), np.float32)
                for _ in range(3):
                    s.run(None, {inp.name: x})  # the first runs set things up (a big chip takes longer): not counted
                t = time.perf_counter()
                for _ in range(5):
                    s.run(None, {inp.name: x})
                ms = (time.perf_counter() - t) / 5 * 1000
                if ms < best[2]:
                    best = (s, f"graphics chip {dev}", ms)
            except Exception:  # no chip with this number (they're numbered from 0, so none after it either)
                break
        return best[0], best[1]

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

    def __init__(self, cam, model=None, sha256=None, on_result=None, on_floor=None, practice=None,
                 settings=SETTINGS):
        self.settings_path = settings
        self.choice = load_settings(settings) if model is None else {"model": "nano", "chip": "cpu"}
        self.cam = cam
        self.model = model or model_path(self.choice["model"])
        self.sha256 = sha256 if sha256 is not None else MODEL_SHA256 if model is not None else MODELS[self.choice["model"]]["sha256"]
        self.on_result = on_result  # called with each picture's items, e.g. to put them on the map
        self.on_floor = on_floor    # called with each free-floor scan, and with None when the scan stops
        self.practice = practice    # returns a floor.Picture of the practice room while Practice is on, else None
        self.scanner = floor.Scanner()
        self.floor_until = 0.0
        self.floor_result, self.floor_error, self.floor_times = None, None, []
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
            d, choice = self.detector, dict(self.choice)
        models = [{"name": n, "label": m["label"], "mb": round(m["size"] / 1e6, 1), "input": m["input"],
                   "accuracy": m["accuracy"], "downloaded": os.path.isfile(model_path(n))} for n, m in MODELS.items()]
        return {"available": not miss, "missing": miss, "setup": SETUP if miss else None,
                "running": running, "labels": len(LABELS), "models": models, "choice": choice,
                "gpu": gpu_available(), "where": d.where if d else None}

    def choose(self, model, chip):
        """The owner picks a model and where it runs. The next picture loads it."""
        if model not in MODELS or chip not in CHIPS:
            return {"ok": False, "error": "Unknown model or chip."}
        if not os.path.isfile(model_path(model)):
            return {"ok": False, "error": f"The {MODELS[model]['label'].lower()} model ({model}) isn't downloaded yet. "
                                          f"Run python pc/tools/get_model.py --model {model}."}
        if chip == "gpu" and not gpu_available():
            return {"ok": False, "error": "No graphics chip to use: install onnxruntime-directml (see docs/VISION.md)."}
        with self.lock:
            self.choice = {"model": model, "chip": chip}
            self.model, self.sha256 = model_path(model), MODELS[model]["sha256"]
            self.detector, self.failed_at, self.error = None, -1e9, None  # loaded afresh with the new choice
            self.result, self.times = None, []
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(self.choice, f)
        except OSError:
            pass
        return {"ok": True, "choice": dict(self.choice)}

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

    def _floor_missing(self):
        return importlib.util.find_spec("PIL") is None and not (self.practice and self.practice() is not None)

    def watch_floor(self):
        """The page asks for the free-floor scan to keep going. Returns its latest result."""
        now = time.monotonic()
        if self._floor_missing():
            return {"ok": False, "error": "Watching the floor needs Pillow on this laptop.", "setup": SETUP}
        with self.lock:
            was = now <= self.floor_until
            self.floor_until = now + KEEP_ALIVE
            if not was:
                self.floor_result, self.floor_error, self.floor_times = None, None, []
                self.scanner.reset()  # the floor's look is learned again: it may be another room
            if self.worker is None:
                self.worker = threading.Thread(target=self._work, name="vision", daemon=True)
                self.worker.start()
            r = dict(self.floor_result or {})
            recent = [t for t in self.floor_times if now - t < 2.0]
            r.update({"ok": True, "on": True, "error": self.floor_error or (self.error if not r else None),
                      "fps": round(len(recent) / 2.0, 1), "age": round(now - r["at"], 2) if "at" in r else None})
            r.pop("at", None)
            return r

    def _wanted(self):
        """(recognition wanted, floor scan wanted). When neither is, the worker ends."""
        now = time.monotonic()
        with self.lock:
            recog, flo = now <= self.until, now <= self.floor_until
            if not (recog or flo):
                self.worker = None  # under the lock, so the next poll starts a fresh worker
            return recog, flo

    def _read_practice(self, stop):
        """The practice room through the pretend camera, 10 pictures a second."""
        while not stop.is_set():
            pic = self.practice() if self.practice else None
            if pic is None:
                return
            with self.new_frame:
                self.frame, self.seq = pic, self.seq + 1
                self.new_frame.notify_all()
            stop.wait(0.1)

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

    def _recognise(self, jpeg):
        """One picture through the model. False if the model wouldn't load or run: recognition
        then stops, and the next poll may try again after a few seconds."""
        try:
            d = self.detector
            if d is None:
                if time.monotonic() - self.failed_at < FAIL_WAIT:
                    return True  # it failed a moment ago: keep its error readable for a while
                with self.lock:
                    path, sha, chip = self.model, self.sha256, self.choice["chip"]
                d = Detector(path, sha, chip=chip)
                with self.lock:
                    if self.model == path:  # not changed again while it loaded
                        self.detector = d
            t0 = time.monotonic()
            try:
                items, size = d(jpeg)
            except (OSError, ValueError, SyntaxError):
                return True  # a frame Pillow can't read; the next one will do
        except Exception as e:
            with self.lock:
                self.error = str(e) if isinstance(e, VisionError) else f"Object recognition stopped: {e}"
                self.until = 0.0
                self.failed_at = time.monotonic()
            return False
        t1 = time.monotonic()
        with self.lock:
            self.result = {"items": items, "size": list(size), "ms": round((t1 - t0) * 1000, 1), "at": t1,
                           "model": self.choice["model"], "where": d.where}
            self.times = [t for t in self.times if t1 - t < 2.0] + [t1]
            self.error = None
        if self.on_result:
            try:
                self.on_result(items)
            except Exception:  # a listener's mistake must not stop recognition
                pass
        return True

    def _scan(self, frame):
        t0 = time.monotonic()
        try:
            pic = frame if isinstance(frame, floor.Picture) else floor.from_jpeg(frame)
        except (OSError, ValueError, SyntaxError):
            return  # a frame Pillow can't read
        except ImportError:
            with self.lock:
                self.floor_error = "Watching the floor needs Pillow on this laptop."
            return
        scan = self.scanner.scan(pic)
        t1 = time.monotonic()
        with self.lock:
            self.floor_result = dict(scan, ms=round((t1 - t0) * 1000), at=t1,
                                     source="practice" if isinstance(frame, floor.Picture) else "camera")
            self.floor_times = [t for t in self.floor_times if t1 - t < 2.0] + [t1]
            self.floor_error = None
        if self.on_floor:
            try:
                self.on_floor(scan)
            except Exception:  # a listener's mistake must not stop the scan
                pass

    def _work(self):
        stop, reader, next_try, source = threading.Event(), None, 0.0, None
        with self.lock:
            # a frame left from an earlier run may be from another camera, or minutes old
            self.frame, seen = None, self.seq
        scanned = False
        try:
            while True:
                recog, flo = self._wanted()
                if not (recog or flo):
                    break
                # Practice watches the practice room: the real camera sees another room than the pretend robot's
                want = "practice" if self.practice and self.practice() is not None else "camera"
                if want != source:
                    stop.set()
                    reader, next_try, source = None, 0.0, want
                if reader is None or not reader.is_alive():
                    if time.monotonic() >= next_try:
                        stop = threading.Event()
                        read = self._read_practice if source == "practice" else self._read
                        reader = threading.Thread(target=read, args=(stop,), name="vision-camera", daemon=True)
                        reader.start()
                        next_try = time.monotonic() + RETRY
                with self.new_frame:
                    self.new_frame.wait_for(lambda: self.seq != seen or time.monotonic() > max(self.until, self.floor_until),
                                            timeout=0.5)
                    if self.seq == seen:
                        continue
                    frame, seen = self.frame, self.seq
                t0 = time.monotonic()
                if recog and isinstance(frame, bytes) and not self._recognise(frame):
                    if not flo:
                        break
                if flo:
                    self._scan(frame)
                    scanned = True
                elif scanned:
                    scanned = False
                    self._floor_ended()
                rest = 1.0 / MAX_RATE - (time.monotonic() - t0)
                if rest > 0:
                    time.sleep(rest)
        finally:
            stop.set()
            with self.lock:
                if self.worker is threading.current_thread():
                    self.worker = None  # not one a newer poll has started meanwhile
            if scanned:
                self._floor_ended()

    def _floor_ended(self):
        if self.on_floor:
            try:
                self.on_floor(None)  # the scan stopped on purpose: the map and brake stop using it
            except Exception:
                pass
