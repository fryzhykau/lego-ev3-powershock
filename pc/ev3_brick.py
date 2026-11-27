"""Talking to the EV3 brick itself: SSH (details, WiFi, uploads) and the leJOS menu over RMI
(battery, versions, start/stop programs).

leJOS 0.9.1 runs dropbear 0.51 from 2008: user root, empty password, and only legacy
algorithms, so the SSH options below re-enable those. The empty password is supplied
through SSH_ASKPASS so nothing ever waits on a prompt.
"""

import atexit
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIB = os.path.join(ROOT, "lib")
TOOLS_SRC = os.path.join(HERE, "tools", "BrickMenu.java")
TOOLS_OUT = os.path.join(ROOT, "out", "tools")
PROGRAMS_DIR = "/home/lejos/programs"
LEJOS_BIN = "/home/root/lejos/bin"
JARS = ["powershock-wifi.jar", "powershock-bt.jar", "powershock-ports.jar"]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_SSH_OPTS = [
    "-o", "LogLevel=ERROR", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=NUL",
    "-o", "ConnectTimeout=6", "-o", "ServerAliveInterval=5",
    "-o", "KexAlgorithms=+diffie-hellman-group1-sha1,diffie-hellman-group14-sha1",
    "-o", "HostKeyAlgorithms=+ssh-rsa", "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa",
    "-o", "Ciphers=+aes128-cbc,3des-cbc", "-o", "MACs=+hmac-sha1",
    "-o", "PreferredAuthentications=password", "-o", "NumberOfPasswordPrompts=1",
]
_askpass = None
_askpass_lock = threading.Lock()


class BrickError(Exception):
    pass


def _ssh_exe():
    win = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "OpenSSH", "ssh.exe")
    return win if os.path.exists(win) else "ssh"


def _askpass_path():
    global _askpass
    with _askpass_lock:
        if not _askpass:
            fd, path = tempfile.mkstemp(prefix="powershock-askpass-", suffix=".cmd")
            os.write(fd, b"@echo.\r\n")  # leJOS root has an empty password
            os.close(fd)
            _askpass = path
            atexit.register(lambda: os.path.exists(path) and os.remove(path))
        return _askpass


def ssh(host, command, stdin=None, timeout=30):
    """Runs a shell command on the brick. stdin may be bytes. Returns stdout text."""
    env = dict(os.environ, SSH_ASKPASS=_askpass_path(), SSH_ASKPASS_REQUIRE="force", DISPLAY=":0")
    try:
        p = subprocess.run([_ssh_exe(), *_SSH_OPTS, f"root@{host}", command], input=stdin or b"",
                           capture_output=True, timeout=timeout, env=env, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise BrickError(f"the brick at {host} didn't answer in {timeout} s")
    if p.returncode == 255:
        err = p.stderr.decode("utf-8", "replace").strip().splitlines()
        raise BrickError(f"can't log in to {host}: {err[-1] if err else 'ssh failed'}")
    return p.stdout.decode("utf-8", "replace")


# ---------- RMI helper (battery, versions, run/stop) ----------

def _jdk_bin():
    home = os.environ.get("JAVA_HOME")
    if not home:
        jdks = os.path.join(os.path.expanduser("~"), ".jdks")
        if os.path.isdir(jdks):
            cands = sorted(os.listdir(jdks), reverse=True)
            home = os.path.join(jdks, cands[0]) if cands else None
    if home:
        return os.path.join(home, "bin")
    import shutil
    javac = shutil.which("javac")
    return os.path.dirname(javac) if javac else None


def _ensure_tool():
    cls = os.path.join(TOOLS_OUT, "BrickMenu.class")
    if os.path.exists(cls) and os.path.getmtime(cls) >= os.path.getmtime(TOOLS_SRC):
        return
    jb = _jdk_bin()
    if not jb:
        raise BrickError("no JDK found for the leJOS menu helper")
    os.makedirs(TOOLS_OUT, exist_ok=True)
    p = subprocess.run([os.path.join(jb, "javac"), "-nowarn", "-cp", os.path.join(LIB, "ev3classes.jar"),
                        "-d", TOOLS_OUT, TOOLS_SRC], capture_output=True, text=True, creationflags=NO_WINDOW)
    if p.returncode:
        raise BrickError("couldn't compile BrickMenu: " + p.stderr.strip())


def menu(host, *args, timeout=20):
    """Calls the leJOS menu over RMI through pc/tools/BrickMenu.java. Returns its JSON.
    Needs a JDK; without one the rest of the console still works."""
    try:
        _ensure_tool()
    except BrickError as e:
        return {"ok": False, "error": str(e)}
    cp = os.pathsep.join([TOOLS_OUT, os.path.join(LIB, "ev3classes.jar")])
    try:
        p = subprocess.run([os.path.join(_jdk_bin(), "java"), "-cp", cp, "BrickMenu", host, *args],
                           capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "leJOS menu didn't answer"}
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": False, "error": (p.stderr or "no reply").strip()[:300]}


# ---------- details ----------

_DETAILS_SH = r"""
v() { printf '%s=%s\n' "$1" "$2"; }
v hostname "$(hostname)"
v kernel "$(uname -r)"
v uptime "$(cut -d' ' -f1 /proc/uptime)"
v memTotal "$(awk '/MemTotal/{print $2}' /proc/meminfo)"
v memFree "$(awk '/MemFree/{f=$2} /^Cached/{c=$2} END{print f+c}' /proc/meminfo)"
v disk "$(df -k 2>/dev/null | awk '$NF=="/"{print $2" "$4; exit}')"
v java "$(ls -d /home/root/lejos/ejre* 2>/dev/null | head -1 | sed 's#.*/##')"
v wlan "$(ifconfig -a | grep -c '^wlan0')"
v dongle "$(dmesg | sed -n 's/.*ieee80211 phy0: //p' | tail -1)"
v wlanIp "$(ifconfig wlan0 2>/dev/null | sed -n 's/.*inet addr:\([0-9.]*\).*/\1/p')"
v wlanState "$(wpa_cli -i wlan0 status 2>/dev/null | sed -n 's/^wpa_state=//p')"
v wlanSsid "$(wpa_cli -i wlan0 status 2>/dev/null | sed -n 's/^ssid=//p')"
v savedSsid "$(sed -n 's/^[[:space:]]*ssid="\(.*\)"$/\1/p' /home/root/lejos/config/wpa_supplicant.conf 2>/dev/null | head -1)"
v btMac "$(hciconfig hci0 2>/dev/null | sed -n 's/.*BD Address: \([0-9A-Fa-f:]*\).*/\1/p')"
v btUp "$(hciconfig hci0 2>/dev/null | grep -c 'UP RUNNING')"
v panIp "$(ifconfig br0 2>/dev/null | sed -n 's/.*inet addr:\([0-9.]*\).*/\1/p')"
v panClients "$(ls /sys/class/net 2>/dev/null | grep -c bnep)"
v receiver "$(netstat -ltn 2>/dev/null | grep -c ':5000 ')"
for f in /home/lejos/programs/powershock-*.jar; do [ -f "$f" ] && v "md5:${f##*/}" "$(md5sum "$f" | cut -d' ' -f1)"; done
"""


def _md5(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def jar_version(path):
    """The version build.ps1 stamped into a jar (powershock/version.txt), or None."""
    try:
        with zipfile.ZipFile(path) as z:
            return z.read("powershock/version.txt").decode("ascii").strip()[:32] or None
    except (OSError, KeyError, zipfile.BadZipFile, UnicodeDecodeError):
        return None


def details(host):
    out = {"host": host}
    try:
        raw = ssh(host, "sh -s", stdin=_DETAILS_SH.encode(), timeout=25)
    except BrickError as e:
        return {"host": host, "ok": False, "error": str(e)}
    kv = {}
    for line in raw.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            kv[k] = v.strip()
    disk = (kv.get("disk") or "").split()
    builds = {}
    for jar in JARS:
        local = _md5(os.path.join(ROOT, "out", jar))
        remote = kv.get("md5:" + jar)
        builds[jar] = {"onBrick": bool(remote), "current": bool(remote and local and remote == local),
                       "built": bool(local), "version": jar_version(os.path.join(ROOT, "out", jar))}
    out.update({
        "ok": True,
        "name": kv.get("hostname"),
        "kernel": kv.get("kernel"),
        "uptimeS": float(kv.get("uptime") or 0),
        "memTotalKb": int(kv.get("memTotal") or 0), "memFreeKb": int(kv.get("memFree") or 0),
        "diskTotalKb": int(disk[0]) if len(disk) > 1 else None, "diskFreeKb": int(disk[1]) if len(disk) > 1 else None,
        "java": kv.get("java"),
        "wifi": {"dongle": kv.get("dongle") or None, "present": kv.get("wlan") == "1", "ip": kv.get("wlanIp") or None,
                 "state": kv.get("wlanState") or None, "ssid": kv.get("wlanSsid") or None,
                 "saved": kv.get("savedSsid") or None},
        "bluetooth": {"mac": (kv.get("btMac") or "").upper() or None, "up": kv.get("btUp") == "1",
                      "ip": kv.get("panIp") or None, "clients": int(kv.get("panClients") or 0)},
        "receiverListening": kv.get("receiver") not in (None, "", "0"),
        "builds": builds,
    })
    m = menu(host, "info")
    out["menu"] = m if m.get("ok") else {"ok": False, "error": m.get("error")}
    return out


# ---------- programs ----------

def upload(host, jars=JARS):
    done = []
    for jar in jars:
        path = os.path.join(ROOT, "out", jar)
        if not os.path.exists(path):
            raise BrickError(f"{jar} isn't built yet")
        with open(path, "rb") as f:
            data = f.read()
        ssh(host, f"cat > {PROGRAMS_DIR}/{jar}.part && mv {PROGRAMS_DIR}/{jar}.part {PROGRAMS_DIR}/{jar}",
            stdin=data, timeout=60)
        done.append(jar)
    return done


def _receiver_up(host):
    return ssh(host, "netstat -ltn 2>/dev/null | grep -c ':5000 '", timeout=15).strip() not in ("", "0")


def run(host, jar="powershock-wifi.jar", wait_s=40):
    """Starts a program on the brick with the same jrun the leJOS menu uses. (Asking the menu
    over RMI was accepted but often ignored, so we start it over SSH directly.) The EV3 takes
    10-30 s to start Java."""
    if jar not in JARS:
        raise BrickError(f"unknown program {jar}")
    import time
    stop(host)
    ssh(host, f"cd {PROGRAMS_DIR} && ( {LEJOS_BIN}/jrun -jar {jar} > /tmp/powershock.out 2>&1 & ) ; true", timeout=20)
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if _receiver_up(host):
            return {"ok": True}
        time.sleep(1.5)
    log = ssh(host, "tail -c 600 /tmp/powershock.out 2>/dev/null", timeout=15).strip()
    return {"ok": False, "error": "the program didn't start" + (f": {log}" if log else "")}


def stop(host):
    menu(host, "stop")
    # busybox ps truncates command lines, so match on /proc/<pid>/cmdline instead.
    ssh(host, "for d in /proc/[0-9]*; do [ ${d#/proc/} != $$ ] && grep -q 'powershock-' $d/cmdline 2>/dev/null && kill ${d#/proc/}; done; "
              "sleep 1; true", timeout=20)
    return {"ok": True}


# ---------- ports ----------

def ports(host):
    """Runs PortProbe on the brick (about 5-10 s: the EV3 starts Java slowly)."""
    raw = ssh(host, f"cd {PROGRAMS_DIR} && {LEJOS_BIN}/jrun -jar powershock-ports.jar 2>/tmp/ports.err", timeout=60)
    line = next((l for l in reversed(raw.splitlines()) if l.startswith("{")), None)
    if not line:
        err = ssh(host, "tail -c 400 /tmp/ports.err", timeout=15).strip()
        raise BrickError("port check failed" + (f": {err}" if err else ""))
    return {k: describe_port(k, v) for k, v in json.loads(line).items()}


_UART = {
    "COL-REFLECT": "Color sensor", "COL-AMBIENT": "Color sensor", "COL-COLOR": "Color sensor",
    "US-DIST-CM": "Ultrasonic sensor", "US-DIST-IN": "Ultrasonic sensor", "US-LISTEN": "Ultrasonic sensor",
    "GYRO-ANG": "Gyro sensor", "GYRO-RATE": "Gyro sensor", "GYRO-G&A": "Gyro sensor",
    "IR-PROX": "Infrared sensor", "IR-SEEK": "Infrared sensor", "IR-REMOTE": "Infrared sensor",
}


def describe_port(port, sig):
    kind, _, detail = (sig or "").partition(":")
    motor = not port.startswith("S")
    if sig.startswith("ERROR:DeviceException"):
        # A running program has the port open, so leJOS won't let anyone else probe it.
        return {"connected": None, "label": "In use by a program", "kind": "busy", "raw": sig}
    if kind in ("NONE", ""):
        return {"connected": False, "label": "Empty", "kind": "none", "raw": sig}
    if kind == "OUTPUT_TACHO":
        label = {"TACHO": "Large motor", "MINITACHO": "Medium motor", "NEWTACHO": "Motor"}.get(detail, "Motor")
        return {"connected": True, "label": label, "kind": "motor", "raw": sig}
    if kind.startswith("OUTPUT"):
        return {"connected": True, "label": "Unknown output device", "kind": "motor", "raw": sig}
    if kind == "UART":
        return {"connected": True, "label": _UART.get(detail, "EV3 sensor"), "kind": "sensor",
                "mode": detail or None, "raw": sig}
    if kind == "EV3_ANALOG":
        return {"connected": True, "label": "Touch sensor" if "TOUCH" in detail else "EV3 analog sensor",
                "kind": "sensor", "raw": sig}
    if kind == "NXT_ANALOG":
        return {"connected": True, "label": "NXT " + detail.replace("NXT_", "").lower() + " sensor",
                "kind": "sensor", "raw": sig}
    if kind == "NXT_COLOR":
        return {"connected": True, "label": "NXT color sensor", "kind": "sensor", "raw": sig}
    if kind == "IIC":
        return {"connected": True, "label": "I2C sensor", "kind": "sensor", "mode": detail or None, "raw": sig}
    return {"connected": kind not in ("UNKNOWN", "ERROR"), "label": "Unknown device" if motor else "Unknown sensor",
            "kind": "unknown", "raw": sig}


# Codes from the EV3's connection manager, as streamed live by the receiver (PortWatch.java).
CONN = {125: "tacho", 124: "output-smart", 123: "output-dumb", 122: "uart", 121: "ev3-analog",
        120: "nxt-i2c", 119: "nxt-analog", 118: "nxt-color", 117: "daisychain", 126: "none",
        127: "error", 111: "unknown"}
TYPES = {7: "Large motor", 8: "Medium motor", 9: "Motor", 1: "NXT touch sensor", 2: "NXT light sensor",
         3: "NXT sound sensor", 4: "NXT color sensor", 5: "NXT ultrasonic sensor", 16: "Touch sensor",
         29: "Color sensor", 30: "Ultrasonic sensor", 32: "Gyro sensor", 33: "Infrared sensor",
         99: "Energy meter", 100: "I2C sensor"}


def describe_live(conn, typ):
    """Turns the two numbers the brick reports for a port into a description."""
    c = CONN.get(conn, "unknown")
    if c == "none":
        return {"connected": False, "label": "Empty", "kind": "none"}
    if c in ("error", "unknown"):
        return {"connected": None, "label": "Can't tell", "kind": "unknown"}
    if c == "tacho":
        return {"connected": True, "label": TYPES.get(typ, "Motor"), "kind": "motor"}
    if c.startswith("output"):
        return {"connected": True, "label": "Output device", "kind": "motor"}
    label = TYPES.get(typ)
    if not label:
        label = {"uart": "EV3 sensor", "ev3-analog": "Touch sensor", "nxt-i2c": "I2C sensor",
                 "nxt-color": "NXT color sensor", "nxt-analog": "NXT sensor"}.get(c, "Sensor")
    return {"connected": True, "label": label, "kind": "sensor"}


SENSOR_KINDS = ("ir", "us", "col", "gy")


def parse_telemetry(line):
    """'T 8.61 0.162 0.000 A=126:126 ... 4=126:126' -> dict, or None."""
    p = line.split()
    if len(p) < 12 or p[0] != "T":
        return None
    try:
        out = {"battery": {"volts": float(p[1]), "batteryAmps": float(p[2]), "motorAmps": float(p[3])},
               "ports": {}}
        for item in p[4:12]:
            name, _, codes = item.partition("=")
            held = codes.endswith("h")
            conn, _, typ = codes.rstrip("h").partition(":")
            key = name if name.isalpha() else "S" + name
            if held and int(conn) == 0:
                d = {"connected": None, "label": "Unknown (port in use)", "kind": "busy"}
            else:
                d = describe_live(int(conn), int(typ))
            d["held"] = held  # PowerShock has this port open; device as seen when it started
            d["codes"] = [int(conn), int(typ)]
            out["ports"][key] = d
        for item in p[12:]:
            # " mB=<tacho deg>:<speed deg/s>:<stalled>" for the motors PowerShock drives
            if item.startswith("m") and "=" in item:
                name, _, vals = item[1:].partition("=")
                v = vals.split(":")
                if len(v) >= 3:
                    out.setdefault("motors", {})[name] = {
                        "tacho": int(v[0]), "speed": int(v[1]), "stalled": v[2] == "1",
                        "role": {"L": "left", "R": "right", "X": "aux"}.get(v[3] if len(v) > 3 else "", None)}
            # " s4=ir:37", " s3=col:5", " s2=us:123", " s1=gy:-45": sensor readings for the map
            elif item.startswith("s") and item[1:2].isdigit() and "=" in item:
                name, _, vals = item[1:].partition("=")
                kind, _, val = vals.partition(":")
                if kind in SENSOR_KINDS and name in "1234":
                    out.setdefault("sensors", {})["S" + name] = {"kind": kind, "value": int(val)}
            # " w=-62": the WiFi signal in dBm (brick 0.8 and later)
            elif item.startswith("w="):
                out["wifi"] = int(item[2:])
        return out
    except ValueError:
        return None


WRONG_AFTER_S = 3.0  # an EV3 sensor takes a second or two to say what it is: no warning while it starts up


class PortCheck:
    """Notices a device in the wrong kind of port. Motor and sensor cables are the same, and a motor in
    a sensor port isn't reported as a motor: the brick sees something there it can't identify. So a
    sensor port that stays unidentifiable probably holds a motor, and a motor port with anything but a
    motor in it probably holds a sensor."""

    def __init__(self):
        self.since = {}  # port -> when it first looked wrong

    def update(self, ports, now):
        """{port: what to do} for the ports that have looked wrong for a while."""
        out = {}
        for p, d in (ports or {}).items():
            sensor_port = p.startswith("S")
            if d.get("held") or d.get("connected") is False:  # held: PowerShock opened it, so it's in use as meant
                wrong = False
            elif sensor_port:
                wrong = d.get("kind") == "unknown"
            else:
                wrong = d.get("kind") != "motor"
            if not wrong:
                self.since.pop(p, None)
                continue
            first = self.since.setdefault(p, now)
            if now - first >= WRONG_AFTER_S:
                out[p] = ("The brick can't identify what's in this sensor port. If it's a motor, move it to A, B, C or D."
                          if sensor_port else
                          "This isn't a motor. If it's a sensor, move it to port 1, 2, 3 or 4.")
        return out


# ---------- WiFi ----------

def wifi_scan(host):
    raw = ssh(host, "wpa_cli -i wlan0 scan >/dev/null 2>&1; sleep 7; wpa_cli -i wlan0 scan_results", timeout=30)
    best = {}
    for line in raw.splitlines()[1:]:
        p = line.split("\t")
        if len(p) < 5 or not p[4].strip():
            continue  # hidden networks have no name; these are what confuse the leJOS menu
        ssid, flags = p[4], p[3]
        try:
            sig = int(p[2])
        except ValueError:
            continue
        if "EAP" in flags:
            kind = "enterprise"
        elif "WPA2-PSK" in flags or "WPA-PSK" in flags:
            kind = "wpa"
        elif "WEP" in flags:
            kind = "wep"
        else:
            kind = "open"
        if ssid not in best or sig > best[ssid]["signal"]:
            best[ssid] = {"ssid": ssid, "signal": sig, "security": kind,
                          "channel": _channel(p[1])}
    return sorted(best.values(), key=lambda n: -n["signal"])


def _channel(freq):
    try:
        f = int(freq)
    except ValueError:
        return None
    return 14 if f == 2484 else (f - 2407) // 5 if f < 3000 else None


_WPA_SIMPLE = {"n": 10, "r": 13, "t": 9, "e": 27, "\\": 92, '"': 34}


def _wpa_bytes(s):
    """wpa_cli prints SSIDs with C-style escapes (\\xNN, \\n, \\", \\\\). Turn them back into
    the real bytes the network broadcasts, which is what the config and the key need."""
    out, i = bytearray(), 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            n = s[i + 1]
            h = s[i + 2:i + 4]
            if n == "x" and len(h) == 2 and all(c in "0123456789abcdefABCDEF" for c in h):
                out.append(int(h, 16))
                i += 4
                continue
            if n in _WPA_SIMPLE:
                out.append(_WPA_SIMPLE[n])
                i += 2
                continue
        out += s[i].encode("utf-8")
        i += 1
    return bytes(out)


WPA_CONF = "/home/root/lejos/config/wpa_supplicant.conf"


def conf_networks(conf):
    """The network={...} blocks of a wpa_supplicant.conf, each as (SSID bytes or None, block text)."""
    out, i = [], 0
    while True:
        start = conf.find("network={", i)
        if start < 0:
            return out
        end = conf.find("}", start)
        if end < 0:
            return out
        block = conf[start:end + 1]
        ssid = None
        for line in block.splitlines():
            k, _, v = line.strip().partition("=")
            if k == "ssid":
                if len(v) >= 2 and v[0] == v[-1] == '"':
                    ssid = v[1:-1].encode("utf-8")
                else:
                    try:
                        ssid = bytes.fromhex(v)
                    except ValueError:
                        ssid = None
        out.append((ssid, block))
        i = end + 1


def conf_with(conf, ssid_raw, block):
    """The config with this network added (or replaced), every other saved network kept.
    block None: the network removed."""
    nets = [b for s, b in conf_networks(conf) if s != ssid_raw]
    if block:
        nets.append(block)
    return "ctrl_interface=/var/run/wpa_supplicant\n\n" + "\n\n".join(nets) + ("\n" if nets else "")


def wifi_saved(host):
    """The names of the WiFi networks saved on the brick. Only the names are read, never the keys."""
    raw = ssh(host, f"sed -n 's/^[[:space:]]*ssid=//p' {WPA_CONF} 2>/dev/null", timeout=15)
    out = []
    for v in raw.splitlines():
        v = v.strip()
        try:
            name = v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else bytes.fromhex(v).decode("utf-8", "replace")
        except ValueError:
            continue
        if name and name not in out:
            out.append(name)
    return out


def _write_conf(host, conf, then=""):
    script = (
        f"cat > {WPA_CONF}.new && chmod 600 {WPA_CONF}.new && mv {WPA_CONF}.new {WPA_CONF}" + then
    )
    return ssh(host, script, stdin=conf.encode(), timeout=60)


def _read_conf(host):
    """The brick's WiFi config, to add to or take from. Its keys stay in memory here: they're
    never logged, returned or kept."""
    return ssh(host, f"cat {WPA_CONF} 2>/dev/null", timeout=15)


def wifi_forget(host, ssid):
    """Removes one saved network; the brick stays on the one it's on until that's lost."""
    raw = _wpa_bytes(ssid)
    _write_conf(host, conf_with(_read_conf(host), raw, None), "; wpa_cli -i wlan0 reconfigure >/dev/null 2>&1")
    return {"ok": True, "saved": wifi_saved(host)}


def wifi_join(host, ssid, password, over_wifi=False):
    """Adds a network to the brick's saved ones (the others are kept, so it can move between
    them) and runs leJOS's own startwlan. The password is turned into the WPA key here (PBKDF2,
    as wpa_passphrase does), so it never reaches the brick or any log in plain text. Returns
    the new WiFi address.

    over_wifi: the laptop reaches the brick over the WiFi that's about to restart, so the answer
    would never arrive. The network is saved, WiFi restarts a moment later, and this returns
    at once with "pending"; the console's link finds the brick again. The networks saved before
    are kept, so a wrong password leaves the brick on one of those."""
    raw = _wpa_bytes(ssid)  # the SSID as the radio sends it
    ssid_hex = raw.hex()
    if password:
        if not 8 <= len(password) <= 63:
            raise BrickError("WiFi passwords are 8 to 63 characters")
        psk = hashlib.pbkdf2_hmac("sha1", password.encode("utf-8"), raw, 4096, 32).hex()
        net = f"\tssid={ssid_hex}\n\tkey_mgmt=WPA-PSK\n\tpsk={psk}\n"
    else:
        net = f"\tssid={ssid_hex}\n\tkey_mgmt=NONE\n"
    conf = conf_with(_read_conf(host), raw, f"network={{\n{net}}}")
    if over_wifi:
        _write_conf(host, conf, f"; nohup sh -c 'sleep 2; {LEJOS_BIN}/startwlan' </dev/null >/dev/null 2>&1 &")
        return {"ok": True, "pending": True}
    script = (
        "cat > /home/root/lejos/config/wpa_supplicant.conf.new && "
        "chmod 600 /home/root/lejos/config/wpa_supplicant.conf.new && "
        "mv /home/root/lejos/config/wpa_supplicant.conf.new /home/root/lejos/config/wpa_supplicant.conf && "
        f"{LEJOS_BIN}/startwlan >/dev/null 2>&1; "
        "ifconfig wlan0 | sed -n 's/.*inet addr:\\([0-9.]*\\).*/\\1/p'; "
        "wpa_cli -i wlan0 status | sed -n 's/^wpa_state=//p'"
    )
    out = ssh(host, script, stdin=conf.encode(), timeout=60).split()
    ip = next((x for x in out if x.count(".") == 3), None)
    state = next((x for x in out if x.isupper()), None)
    if ip:
        return {"ok": True, "ip": ip}
    if state in ("4WAY_HANDSHAKE", "DISCONNECTED", "SCANNING"):
        return {"ok": False, "error": f"the brick couldn't join {ssid}. Check the password."}
    return {"ok": False, "error": f"joined {ssid} but got no address (state {state or 'unknown'})."}


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "upload":
        try:
            for j in upload(sys.argv[2]):
                print(f"uploaded {j} to {sys.argv[2]}")
        except BrickError as e:
            print(f"upload failed: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("usage: python ev3_brick.py upload <brick-ip>", file=sys.stderr)
        sys.exit(2)
