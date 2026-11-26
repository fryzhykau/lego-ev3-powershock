"""Checks the files git would publish for private or sensitive data. Run before every commit:

    python pc/tools/privacy_check.py            (exit code 1 if anything is found)

What it looks for, in every file git tracks or would add (not in ignored files):
- files that must never be published: Oracle's Java runtime, leJOS/JNA jars, SD-card backups,
  build output, your own controls and device log
- secrets: GitHub/OpenAI/AWS tokens, private keys, WPA keys
- Bluetooth/MAC addresses, IP addresses and e-mail addresses, except known examples
- Windows home folders (C:\\Users\\<name>), which give away a user name
- anything listed in `.private-terms` at the top of the repository: one word or phrase per
  line (your network names, your brick's address, your name). That file is ignored by git,
  so your private words never get published themselves.

Images can't be read this way: look at every screenshot yourself before committing it.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAX_BYTES = 5 * 1024 * 1024

FORBIDDEN_PATHS = [
    (re.compile(r"(^|/)sd_lejos/"), "a copy of the leJOS SD card (includes Oracle's Java runtime)"),
    (re.compile(r"(^|/)sd_backup"), "an SD-card backup"),
    (re.compile(r"(^|/)lib/[^/]+\.jar$"), "a leJOS/JNA/Java runtime jar (licensed separately)"),
    (re.compile(r"(^|/)rt7?\.jar$"), "Oracle's Java class library"),
    (re.compile(r"\.(bz2|tar\.gz|tgz|img)$"), "an SD-card image or archive"),
    (re.compile(r"(^|/)out/"), "build output"),
    (re.compile(r"(^|/)pc/mapping\.json$"), "your own saved controls"),
    (re.compile(r"(^|/)docs/DEVICE_LOG\.md$"), "your device log (has your brick's addresses)"),
    (re.compile(r"(^|/)\.private-terms$"), "your private terms list"),
    (re.compile(r"(^|/)\.env$|\.pem$|\.key$|(^|/)id_rsa"), "a secrets file"),
    (re.compile(r"(^|/)\.claude/settings\.local\.json$"), "local agent settings"),
]

SECRETS = [
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "a GitHub token"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "an API key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "an AWS key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
    (re.compile(r"\bpsk=[0-9a-fA-F]{64}\b"), "a WPA key"),
]
MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
HOME = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+(?!<|%|\$|Public\b|Default\b)[^\\/\s\"'<>]+", re.I)

# Examples and well-known addresses that are fine to publish.
OK_MACS = {"00:00:00:00:00:00", "AA:BB:CC:DD:EE:FF", "FF:FF:FF:FF:FF:FF"}
OK_IPS = {"127.0.0.1", "0.0.0.0", "10.0.1.1", "10.0.1.2", "255.255.255.255", "255.255.255.0", "192.168.1.40"}
OK_EMAILS = {"noreply@anthropic.com"}
SKIP_SCAN = (re.compile(r"(^|/)pc/console/vendor/"),)  # third-party code, checked when vendored


def published_files():
    """Files git tracks or would add with `git add -A` (ignored files left out)."""
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                         cwd=ROOT, capture_output=True, check=True).stdout
    return sorted({p for p in out.decode("utf-8").split("\0") if p and os.path.isfile(os.path.join(ROOT, p))})


def private_terms():
    path = os.path.join(ROOT, ".private-terms")
    try:
        with open(path, encoding="utf-8") as f:
            return [t.strip() for t in f if t.strip() and not t.startswith("#")]
    except OSError:
        return []


def check_text(rel, text, terms):
    """Problems in one file's text: list of (line number, message)."""
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        for rx, what in SECRETS:
            if rx.search(line):
                found.append((n, what))
        for m in MAC.findall(line):
            if m.upper().replace("-", ":") not in OK_MACS:
                found.append((n, f"a hardware address {m}"))
        for m in IPV4.findall(line):
            parts = [int(x) for x in m.split(".")]
            if all(p <= 255 for p in parts) and m not in OK_IPS and not rel.endswith(".svg"):
                found.append((n, f"an IP address {m}"))
        for m in EMAIL.findall(line):
            if m.lower() not in OK_EMAILS:
                found.append((n, f"an e-mail address {m}"))
        for m in HOME.findall(line):
            found.append((n, f"a home folder {m}"))
        low = line.lower()
        for t in terms:
            if t.lower() in low:
                found.append((n, "a term from .private-terms"))
    return found


def check(files=None, terms=None):
    files = published_files() if files is None else files
    terms = private_terms() if terms is None else terms
    problems = []
    for rel in files:
        for rx, what in FORBIDDEN_PATHS:
            if rx.search(rel):
                problems.append(f"{rel}: must not be published: {what}")
        path = os.path.join(ROOT, rel)
        if os.path.getsize(path) > MAX_BYTES:
            problems.append(f"{rel}: larger than 5 MB")
        if any(rx.search(rel) for rx in SKIP_SCAN):
            continue
        with open(path, "rb") as f:
            raw = f.read()
        if b"\0" in raw[:8192]:
            continue  # binary (images): check by eye
        text = raw.decode("utf-8", "replace")
        problems += [f"{rel}:{n}: {msg}" for n, msg in check_text(rel, text, terms)]
    return problems


def main():
    try:
        problems = check()
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"privacy check couldn't list files (is this a git repository?): {e}")
        return 2
    for p in problems:
        print(p)
    images = [f for f in published_files() if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))]
    if images:
        print(f"{len(images)} image(s) can't be scanned; look at them yourself: " + ", ".join(images))
    print("privacy check: " + (f"{len(problems)} problem(s)" if problems else "clean"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
