#!/usr/bin/env python3
"""PowerShock camera: streams a Raspberry Pi camera to the PowerShock console as MJPEG.

On the Pi (Python 3 standard library only; no installs):

    python3 powershock_cam.py                 port 8080, 640 x 480, 20 frames a second
    python3 powershock_cam.py --flip          camera mounted upside down
    python3 powershock_cam.py --test          no camera: a moving test pattern (needs Pillow)

It uses the camera tool your Raspberry Pi OS already has: rpicam-vid (Bookworm and later),
libcamera-vid (Bullseye) or raspivid (Buster and the legacy camera stack).

Every request needs the access key, as ?key=... or an X-PowerShock-Key header. The key is
made on the first run, saved in ~/.powershock-cam-key (readable only by you) and printed, so you
can type it into the console's Camera setup. Without it, anyone on your network could watch.

  /stream.mjpg   live video (multipart JPEG)
  /snapshot.jpg  the latest picture
  /status        JSON: size, frames a second, which camera tool, clients
  POST /settings {"colours": "normal" | "noir"}: "noir" for a camera without an infrared filter,
                 whose picture otherwise looks pink or purple. Saved in ~/.powershock-cam.json.
"""
import argparse
import glob
import hmac
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

VERSION = "0.8.0"
KEY_FILE = os.path.expanduser("~/.powershock-cam-key")
SETTINGS_FILE = os.path.expanduser("~/.powershock-cam.json")
COLOURS = ("normal", "noir")
TUNING_DIRS = ("/usr/share/libcamera/ipa/rpi/vc4", "/usr/share/libcamera/ipa/rpi/pisp",
               "/usr/local/share/libcamera/ipa/rpi/vc4", "/usr/local/share/libcamera/ipa/rpi/pisp")
BOUNDARY = "powershockframe"
MAX_CLIENTS = 4
SOI, EOI = b"\xff\xd8", b"\xff\xd9"
MAX_FRAME = 4 * 1024 * 1024


def load_key(path=KEY_FILE):
    """The access key: read it, or make one and save it (mode 600)."""
    try:
        with open(path, encoding="ascii") as f:
            key = f.read().strip()
        if len(key) >= 16:
            return key
    except OSError:
        pass
    key = secrets.token_urlsafe(18)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(key + "\n")
    return key


def load_settings(path=SETTINGS_FILE):
    """What the console chose, kept on the Pi so it lasts across restarts."""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    return {"colours": d.get("colours") if d.get("colours") in COLOURS else "normal"}


def save_settings(settings, path=SETTINGS_FILE):
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f)
    os.replace(tmp, path)


def sensor_name():
    """The camera chip, e.g. "ov5647", from the camera tool's list. Asked before the camera starts."""
    for tool in ("rpicam-hello", "libcamera-hello"):
        if shutil.which(tool):
            try:
                out = subprocess.run([tool, "--list-cameras"], capture_output=True, text=True, timeout=20).stdout
            except (OSError, subprocess.SubprocessError):
                continue
            m = re.search(r"^\s*\d+\s*:\s*([A-Za-z0-9_]+)", out, re.M)
            if m:
                return m.group(1).lower()
    return None


def noir_tuning(sensor, dirs=TUNING_DIRS):
    """The camera's own tuning for having no infrared filter (e.g. ov5647_noir.json), if there is one."""
    if not sensor:
        return None
    for d in dirs:
        hits = glob.glob(os.path.join(d, f"{sensor}_noir.json"))
        if hits:
            return hits[0]
    return None


class Frames:
    """The latest JPEG; readers wait for the next one."""

    def __init__(self):
        self.cond = threading.Condition()
        self.jpeg, self.seq, self.at = None, 0, 0.0
        self.times = []
        self.error = None
        self.source = None
        self.proc = None  # the camera tool now running, so a settings change can restart it
        self.colours_note = None

    def put(self, jpeg):
        now = time.monotonic()
        with self.cond:
            self.jpeg, self.seq, self.at = jpeg, self.seq + 1, now
            self.times = [t for t in self.times if now - t < 2.0] + [now]
            self.cond.notify_all()

    def wait(self, after, timeout=2.0):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != after, timeout)
            return self.seq, self.jpeg

    def fps(self):
        with self.cond:
            now = time.monotonic()
            recent = [t for t in self.times if now - t < 2.0]
            return round(len(recent) / 2.0, 1)


def split_jpegs(buf):
    """Takes whole JPEGs off the front of buf. Returns (frames, rest)."""
    frames = []
    while True:
        start = buf.find(SOI)
        if start < 0:
            return frames, b""
        end = buf.find(EOI, start + 2)
        if end < 0:
            rest = buf[start:]
            return frames, (rest if len(rest) <= MAX_FRAME else b"")
        frames.append(buf[start:end + 2])
        buf = buf[end + 2:]


def camera_commands(w, h, fps, flip, quality, tuning=None, greyworld=False):
    """Ways to get MJPEG on stdout, newest camera tool first. tuning: a libcamera tuning file (the
    NoIR one for a camera without an infrared filter); greyworld: the same idea for raspivid."""
    cmds = []
    for tool in ("rpicam-vid", "libcamera-vid"):
        if shutil.which(tool):
            c = [tool, "-t", "0", "-n", "--codec", "mjpeg", "--width", str(w), "--height", str(h),
                 "--framerate", str(fps), "--quality", str(quality), "-o", "-"]
            if flip:
                c += ["--hflip", "--vflip"]
            if tuning:
                c += ["--tuning-file", tuning]
            cmds.append(c)
    if shutil.which("raspivid"):
        c = ["raspivid", "-t", "0", "-n", "-cd", "MJPEG", "-w", str(w), "-h", str(h), "-fps", str(fps), "-o", "-"]
        if flip:
            c += ["-hf", "-vf"]
        if greyworld:
            c += ["-awb", "greyworld"]
        cmds.append(c)
    return cmds


def run_camera(frames, args, stop):
    """Keeps a camera tool running and feeds its frames in; restarts it if it stops."""
    while not stop.is_set():
        noir = args.settings["colours"] == "noir"
        if noir and getattr(args, "tuning", "unknown") == "unknown":
            args.tuning = noir_tuning(sensor_name())  # looked up once, while the camera is free
        tuning = args.tuning if noir else None
        frames.colours_note = ("This camera has no NoIR tuning; colours stay as they are."
                               if noir and not tuning and not shutil.which("raspivid") else None)
        cmds = camera_commands(args.width, args.height, args.fps, args.flip, args.quality, tuning, noir)
        if not cmds:
            frames.error = "no camera tool found (rpicam-vid, libcamera-vid or raspivid)"
            stop.wait(5)
            continue
        for cmd in cmds:
            frames.source = cmd[0]
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
            except OSError as e:
                frames.error = f"{cmd[0]}: {e}"
                continue
            frames.proc = p
            buf, got = b"", 0
            while not stop.is_set():
                chunk = p.stdout.read(65536)
                if not chunk:
                    break
                found, buf = split_jpegs(buf + chunk)
                for jpeg in found:
                    frames.put(jpeg)
                    got += 1
                if got:
                    frames.error = None
            p.kill()
            frames.proc = None
            err = (p.stderr.read() or b"").decode("utf-8", "replace").strip().splitlines()
            if got:
                break  # it worked for a while (or the settings changed): start the same tool again
            frames.error = f"{cmd[0]} gave no pictures: {err[-1] if err else 'no message'}"
        stop.wait(2)


def run_test_pattern(frames, args, stop):
    """No camera: a moving pattern, so the console can be tried anywhere."""
    from PIL import Image, ImageDraw
    frames.source = "test pattern"
    n = 0
    while not stop.is_set():
        im = Image.new("RGB", (args.width, args.height), (32, 36, 40))
        d = ImageDraw.Draw(im)
        for i in range(0, args.width, 40):
            d.line([(i, 0), (i, args.height)], fill=(52, 58, 64))
        for j in range(0, args.height, 40):
            d.line([(0, j), (args.width, j)], fill=(52, 58, 64))
        x = int((n * 6) % (args.width + 80)) - 40
        d.rectangle([x, args.height // 2 - 30, x + 60, args.height // 2 + 30], fill=(209, 36, 47))
        d.text((12, 10), f"PowerShock test camera  {time.strftime('%H:%M:%S')}  frame {n}", fill=(230, 232, 233))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=args.quality)
        frames.put(out.getvalue())
        n += 1
        stop.wait(1.0 / args.fps)


def wifi_signal(path="/proc/net/wireless"):
    """The WiFi signal in dBm, or None without WiFi. The console shows it, to help choose where
    a second router or extender helps."""
    try:
        with open(path, encoding="ascii", errors="replace") as f:
            for line in f:
                name, _, rest = line.strip().partition(":")
                if name == "wlan0":
                    v = int(float(rest.split()[2]))
                    return v - 256 if v > 0 else v
    except (OSError, ValueError, IndexError):
        pass
    return None


def make_handler(frames, key, args):
    clients = threading.BoundedSemaphore(MAX_CLIENTS)

    class Handler(BaseHTTPRequestHandler):
        server_version = "PowerShockCam/" + VERSION

        def log_message(self, fmt, *a):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _allowed(self, url):
            given = self.headers.get("X-PowerShock-Key") or (parse_qs(url.query).get("key") or [""])[0]
            return hmac.compare_digest(given.encode(), key.encode())

        def _status(self):
            return {"ok": frames.jpeg is not None, "version": VERSION, "source": frames.source,
                    "error": frames.error, "width": args.width, "height": args.height,
                    "fps": frames.fps(), "flip": args.flip, "wifi": wifi_signal(),
                    "colours": args.settings["colours"], "coloursNote": frames.colours_note}

        def do_POST(self):
            url = urlparse(self.path)
            if not self._allowed(url):
                return self._send(403, b'{"error": "wrong or missing key"}', "application/json")
            if url.path != "/settings":
                return self._send(404, b'{"error": "not found"}', "application/json")
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n)) if 0 < n <= 4096 else None
                colours = body["colours"]
                if colours not in COLOURS:
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                return self._send(400, b'{"error": "colours must be normal or noir"}', "application/json")
            if colours != args.settings["colours"]:
                args.settings = dict(args.settings, colours=colours)
                try:
                    save_settings(args.settings, args.settings_file)
                except OSError:
                    pass  # it still applies until the streamer restarts
                p = frames.proc
                if p:
                    p.kill()  # the camera loop starts it again with the new setting
            return self._send(200, json.dumps(self._status()).encode(), "application/json")

        def do_GET(self):
            url = urlparse(self.path)
            if not self._allowed(url):
                return self._send(403, b'{"error": "wrong or missing key"}', "application/json")
            if url.path == "/status":
                return self._send(200, json.dumps(self._status()).encode(), "application/json")
            if url.path == "/snapshot.jpg":
                if frames.jpeg is None:
                    return self._send(503, b'{"error": "no picture yet"}', "application/json")
                return self._send(200, frames.jpeg, "image/jpeg")
            if url.path == "/stream.mjpg":
                if not clients.acquire(blocking=False):
                    return self._send(503, b'{"error": "too many viewers"}', "application/json")
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    seq = 0
                    while True:
                        seq, jpeg = frames.wait(seq)
                        if jpeg is None:
                            continue
                        self.wfile.write(f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpeg)}\r\n\r\n".encode())
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                except OSError:
                    pass  # the viewer went away
                finally:
                    clients.release()
                return None
            return self._send(404, b'{"error": "not found"}', "application/json")

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(description="Stream a Raspberry Pi camera to the PowerShock console.")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--bind", default="0.0.0.0", help="address to listen on (default: all)")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--quality", type=int, default=70, help="JPEG quality 10..95")
    ap.add_argument("--flip", action="store_true", help="turn the picture 180 degrees")
    ap.add_argument("--test", action="store_true", help="test pattern instead of the camera (needs Pillow)")
    ap.add_argument("--key-file", default=KEY_FILE)
    ap.add_argument("--settings-file", default=SETTINGS_FILE)
    args = ap.parse_args(argv)
    args.settings = load_settings(args.settings_file)
    args.width = max(160, min(1920, args.width))
    args.height = max(120, min(1080, args.height))
    args.fps = max(1, min(30, args.fps))
    args.quality = max(10, min(95, args.quality))
    key = load_key(args.key_file)
    frames, stop = Frames(), threading.Event()
    threading.Thread(target=run_test_pattern if args.test else run_camera, args=(frames, args, stop), daemon=True).start()
    srv = ThreadingHTTPServer((args.bind, args.port), make_handler(frames, key, args))
    srv.daemon_threads = True
    print(f"PowerShock camera {VERSION}: port {args.port}, {args.width}x{args.height} at {args.fps} fps")
    if sys.stdout.isatty():  # not into a service's log
        print(f"Access key (type it into the console's Camera setup): {key}")
    else:
        print(f"Access key: in {args.key_file}")
    sys.stdout.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        srv.server_close()


if __name__ == "__main__":
    main()
