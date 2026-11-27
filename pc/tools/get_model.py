"""Downloads object recognition models into pc/models/ and checks them.

    python pc/tools/get_model.py                download nano, unless a good copy is already there
    python pc/tools/get_model.py --model s      another size: nano, tiny, s or m
    python pc/tools/get_model.py --all          all four (about 160 MB)
    python pc/tools/get_model.py --check        only check the copies that are there

The models are YOLOX by Megvii (Apache-2.0), from the official YOLOX releases on GitHub:
nano 3.7 MB, tiny 20 MB, s 36 MB, m 101 MB. Their SHA-256 checksums are fixed in pc/vision.py,
so a changed or broken download is refused. The files stay out of git (pc/models/ is ignored).
Setup guide: docs/VISION.md.
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


def get(key, check=False):
    """One model: 0 if it's there and right (downloading it unless check), 1 if not."""
    m = vision.MODELS[key]
    path, name = vision.model_path(key), m["file"]
    there = os.path.isfile(path)
    if there and vision.file_sha256(path) == m["sha256"]:
        print(f"{name} is there and its checksum is right.")
        return 0
    if check:
        print(f"{name} {'has the wrong checksum' if there else 'is not there'}. "
              f"Run python pc/tools/get_model.py --model {key}.")
        return 1
    print(f"Downloading {name} ({m['size'] / 1e6:.1f} MB) from {vision.model_url(key)}")
    try:
        download(vision.model_url(key), path, m["sha256"], m["size"])
    except (OSError, ValueError, urllib.error.URLError) as e:
        print(f"\nCouldn't get {name}: {getattr(e, 'reason', None) or e}. "
              "Check the internet connection and try again; docs/VISION.md has other ways.")
        return 1
    print(f"Saved and checked: pc/models/{name}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Download and check the object recognition models.")
    ap.add_argument("--model", choices=list(vision.MODELS), default="nano", help="which size (default nano)")
    ap.add_argument("--all", action="store_true", help="all sizes")
    ap.add_argument("--check", action="store_true", help="only check the copies that are there")
    args = ap.parse_args(argv)
    keys = list(vision.MODELS) if args.all else [args.model]
    bad = sum(get(k, args.check) for k in keys)
    missing = [m for m in vision.missing() if m != "model"]
    if missing and not args.check:
        print(f"Still needed: {', '.join(missing)}. Run python -m pip install -r pc/requirements-vision.txt")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
