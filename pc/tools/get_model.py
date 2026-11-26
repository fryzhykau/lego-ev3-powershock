"""Downloads the object recognition model into pc/models/ and checks it.

    python pc/tools/get_model.py           download it, unless a good copy is already there
    python pc/tools/get_model.py --check   only check the copy that's there

The model is YOLOX-nano by Megvii (Apache-2.0), 3.7 MB, from the official YOLOX releases on GitHub.
Its SHA-256 checksum is fixed in pc/vision.py, so a changed or broken download is refused.
The file stays out of git (pc/models/ is ignored). Setup guide: docs/VISION.md.
"""
import argparse
import hashlib
import os
import sys
import tempfile
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import vision  # noqa: E402

CHUNK = 1 << 16


def download(url, dest, sha256, size, progress=True):
    """Fetches url into dest, but only keeps it if its checksum matches."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".download-", dir=os.path.dirname(dest))
    try:
        h, got = hashlib.sha256(), 0
        req = urllib.request.Request(url, headers={"User-Agent": "PowerShock-get-model"})
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(req, timeout=60) as resp:
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                got += len(chunk)
                if got > size:
                    raise ValueError(f"the download is bigger than the expected {size} bytes")
                h.update(chunk)
                out.write(chunk)
                if progress:
                    print(f"\r  {got / 1e6:.1f} of {size / 1e6:.1f} MB", end="", flush=True)
        if progress:
            print()
        if h.hexdigest() != sha256:
            raise ValueError("the downloaded file's checksum doesn't match, so it wasn't kept")
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Download and check the object recognition model.")
    ap.add_argument("--check", action="store_true", help="only check the copy that's there")
    args = ap.parse_args(argv)
    name = os.path.basename(vision.MODEL)
    there = os.path.isfile(vision.MODEL)
    if there and vision.file_sha256(vision.MODEL) == vision.MODEL_SHA256:
        print(f"{name} is there and its checksum is right.")
        return 0
    if args.check:
        print(f"{name} {'has the wrong checksum' if there else 'is not there'}. Run python pc/tools/get_model.py.")
        return 1
    print(f"Downloading {name} ({vision.MODEL_SIZE / 1e6:.1f} MB) from {vision.MODEL_URL}")
    try:
        download(vision.MODEL_URL, vision.MODEL, vision.MODEL_SHA256, vision.MODEL_SIZE)
    except (OSError, ValueError, urllib.error.URLError) as e:
        print(f"\nCouldn't get the model: {getattr(e, 'reason', None) or e}. "
              "Check the internet connection and try again; docs/VISION.md has other ways.")
        return 1
    print(f"Saved and checked: pc/models/{name}")
    missing = [m for m in vision.missing() if m != "model"]
    if missing:
        print(f"Still needed: {', '.join(missing)}. Run python -m pip install -r pc/requirements-vision.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
