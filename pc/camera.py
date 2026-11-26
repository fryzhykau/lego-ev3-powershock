"""The robot's camera: a Raspberry Pi running pi/powershock_cam.py, reached over the network.

The console keeps the Pi's address and access key (in pc/camera.json, which git ignores) and
relays the Pi's video to the page, so the page only ever talks to the console.
"""
import http.client
import json
import os
import re
import socket
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "camera.json")
HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
MAX_STREAMS = 3
MAX_FRAME = 8 * 1024 * 1024


class CameraError(Exception):
    pass


def open_socket(host, port, timeout):
    """Like socket.create_connection, but IPv4 addresses first. The Pi's streamer listens on IPv4,
    and a .local name also resolves to an IPv6 address: on Windows each refused IPv6 attempt costs
    about 2 seconds before IPv4 is tried."""
    err = None
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    for fam, kind, proto, _, addr in sorted(infos, key=lambda a: a[0] != socket.AF_INET):
        s = socket.socket(fam, kind, proto)
        s.settimeout(timeout)
        try:
            s.connect(addr)
            return s
        except OSError as e:
            s.close()
            err = e
    raise err or OSError(f"no address for {host}")


class _Connection(http.client.HTTPConnection):
    def connect(self):
        self.sock = open_socket(self.host, self.port, self.timeout)


def read_parts(f):
    """The JPEGs in a multipart/x-mixed-replace body, one at a time, by each part's Content-Length.
    Stops at the end of the stream, or at a part that's cut short or far too big."""
    size = None
    while True:
        line = f.readline(1024)
        if not line:
            return
        head = line.strip().lower()
        if head.startswith(b"content-length:"):
            try:
                size = int(head.split(b":", 1)[1])
            except ValueError:
                size = None
        elif not head and size is not None:
            if not 0 < size <= MAX_FRAME:
                return
            data = f.read(size)
            if len(data) < size:
                return
            yield data
            size = None


def check(host, port, key):
    """Checked settings, or CameraError saying what's wrong."""
    host = (host or "").strip()
    if not HOST_RE.match(host) or ".." in host:
        raise CameraError("Enter the Pi's address, like 192.168.1.40 or raspberrypi.local.")
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise CameraError("The port is a number, usually 8080.") from None
    if not 1 <= port <= 65535:
        raise CameraError("The port is a number from 1 to 65535, usually 8080.")
    key = (key or "").strip()
    if not KEY_RE.match(key):
        raise CameraError("The key is the line the Pi printed when the camera started (16 or more letters and digits).")
    return host, port, key


class Camera:
    def __init__(self, config=CONFIG):
        self.config = config
        self.lock = threading.Lock()
        self.streams = threading.BoundedSemaphore(MAX_STREAMS)
        self.host = self.port = self.key = None
        self._status, self._status_at = None, 0.0
        try:
            with open(config, encoding="utf-8") as f:
                d = json.load(f)
            self.host, self.port, self.key = check(d.get("host"), d.get("port"), d.get("key"))
        except (OSError, ValueError, CameraError):
            pass

    def configured(self):
        return self.host is not None

    def set(self, host, port, key):
        """Saves new settings. An empty key keeps the one already saved."""
        if not (key or "").strip() and self.key:
            key = self.key
        host, port, key = check(host, port, key)
        with self.lock:
            self.host, self.port, self.key = host, port, key
            self._status_at = 0.0
        fd = os.open(self.config, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"host": host, "port": port, "key": key}, f)

    def forget(self):
        with self.lock:
            self.host = self.port = self.key = None
            self._status = None
        try:
            os.remove(self.config)
        except OSError:
            pass

    def _request(self, path, timeout):
        with self.lock:
            host, port, key = self.host, self.port, self.key
        if host is None:
            raise CameraError("No camera set up yet.")
        conn = _Connection(host, port, timeout=timeout)
        try:
            conn.request("GET", path, headers={"X-PowerShock-Key": key})
            resp = conn.getresponse()
        except OSError as e:
            conn.close()
            raise CameraError(f"The camera at {host}:{port} isn't answering ({e.strerror or e}).") from None
        if resp.status == 403:
            conn.close()
            raise CameraError("The camera refused the key. Copy it again from the Pi.")
        return conn, resp

    def status(self, max_age=2.0):
        """What the Pi reports, checked at most every couple of seconds."""
        now = time.monotonic()
        with self.lock:
            if self._status is not None and now - self._status_at < max_age:
                return self._status
            host, port = self.host, self.port
        if host is None:
            return {"configured": False}
        out = {"configured": True, "host": host, "port": port}
        try:
            conn, resp = self._request("/status", 1.5)
            try:
                info = json.loads(resp.read(65536) or b"{}") if resp.status == 200 else {}
            finally:
                conn.close()
            out.update({"reachable": True, "ok": bool(info.get("ok")), "error": info.get("error"),
                        "width": info.get("width"), "height": info.get("height"), "fps": info.get("fps"),
                        "source": info.get("source"), "version": info.get("version")})
        except (CameraError, ValueError) as e:
            out.update({"reachable": False, "ok": False, "error": str(e)})
        with self.lock:
            self._status, self._status_at = out, time.monotonic()
        return out

    def snapshot(self):
        conn, resp = self._request("/snapshot.jpg", 3)
        try:
            if resp.status != 200 or not (resp.getheader("Content-Type") or "").startswith("image/jpeg"):
                raise CameraError("The camera has no picture yet.")
            return resp.read(8 * 1024 * 1024)
        finally:
            conn.close()

    def frames(self, stop):
        """The Pi's live video as single JPEGs, until `stop` (an Event) is set or the video ends.
        It takes one of the camera view slots, like a page showing the video."""
        if not self.streams.acquire(blocking=False):
            raise CameraError("Too many camera views are open.")
        try:
            conn, resp = self._request("/stream.mjpg", 5)
            try:
                if resp.status != 200 or not (resp.getheader("Content-Type") or "").startswith("multipart/x-mixed-replace"):
                    raise CameraError("The camera didn't send video.")
                for jpeg in read_parts(resp):
                    if stop.is_set():
                        break
                    yield jpeg
            except OSError:
                pass  # the Pi went away, or stopped sending for 5 seconds
            finally:
                conn.close()
        finally:
            self.streams.release()

    def relay(self, out, on_start):
        """Copies the Pi's live video to `out` (a file-like) until either side stops.
        on_start(content_type) is called once the Pi has answered."""
        if not self.streams.acquire(blocking=False):
            raise CameraError("Too many camera views are open.")
        try:
            conn, resp = self._request("/stream.mjpg", 5)
            try:
                ctype = resp.getheader("Content-Type") or ""
                if resp.status != 200 or not ctype.startswith("multipart/x-mixed-replace"):
                    raise CameraError("The camera didn't send video.")
                on_start(ctype)
                while True:
                    chunk = resp.read1(65536)
                    if not chunk:
                        break
                    out.write(chunk)
            except OSError:
                pass  # the page closed the view, or the Pi went away
            finally:
                conn.close()
        finally:
            self.streams.release()
