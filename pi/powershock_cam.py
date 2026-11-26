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
"""
import argparse
import hmac
import io
import json
import os
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


class Frames:
    """The latest JPEG; readers wait for the next one."""

    def __init__(self):
        self.cond = threading.Condition()
        self.jpeg, self.seq, self.at = None, 0, 0.0
        self.times = []
        self.error = None
        self.source = None

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


def camera_commands(w, h, fps, flip, quality):
    """Ways to get MJPEG on stdout, newest camera tool first."""
    cmds = []
    for tool in ("rpicam-vid", "libcamera-vid"):
        if shutil.which(tool):
            c = [tool, "-t", "0", "-n", "--codec", "mjpeg", "--width", str(w), "--height", str(h),
                 "--framerate", str(fps), "--quality", str(quality), "-o", "-"]
            if flip:
                c += ["--hflip", "--vflip"]
            cmds.append(c)
    if shutil.which("raspivid"):
        c = ["raspivid", "-t", "0", "-n", "-cd", "MJPEG", "-w", str(w), "-h", str(h), "-fps", str(fps), "-o", "-"]
        if flip:
            c += ["-hf", "-vf"]
        cmds.append(c)
    return cmds


def run_camera(frames, args, stop):
    """Keeps a camera tool running and feeds its frames in; restarts it if it stops."""
    while not stop.is_set():
        cmds = camera_commands(args.width, args.height, args.fps, args.flip, args.quality)
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
            err = (p.stderr.read() or b"").decode("utf-8", "replace").strip().splitlines()
            if got:
                break  # it worked for a while: start the same tool again
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

        def do_GET(self):
            url = urlparse(self.path)
            given = self.headers.get("X-PowerShock-Key") or (parse_qs(url.query).get("key") or [""])[0]
            if not hmac.compare_digest(given.encode(), key.encode()):
                return self._send(403, b'{"error": "wrong or missing key"}', "application/json")
            if url.path == "/status":
                body = {"ok": frames.jpeg is not None, "version": VERSION, "source": frames.source,
                        "error": frames.error, "width": args.width, "height": args.height,
                        "fps": frames.fps(), "flip": args.flip}
                return self._send(200, json.dumps(body).encode(), "application/json")
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
    args = ap.parse_args(argv)
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
