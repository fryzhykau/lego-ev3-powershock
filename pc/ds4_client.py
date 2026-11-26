"""PC side of the WiFi variant: reads a DualShock 4 on Windows and drives the EV3.

    python ds4_client.py <EV3-IP>          drive (EV3 must be running DS4Receiver)
    python ds4_client.py --show            print raw axes/buttons to check the mapping

Pair the DS4 with Windows first (hold Share + PS, then add it in Bluetooth settings),
or plug it in with a USB cable.

Controls: left stick drives (B/C), right stick Y moves motor A, R2 = turbo,
Cross (X) = emergency stop while held, Options = quit.
"""

import argparse
import socket
import sys
import time

import pygame

from ds4_mix import mix

PORT = 5000
RATE_HZ = 50

# Indexes for SDL2's DS4 driver (pygame 2 on Windows). Check with --show and
# adjust if your setup reports different numbers.
AXIS_LX, AXIS_LY, AXIS_RX, AXIS_RY, AXIS_L2, AXIS_R2 = 0, 1, 2, 3, 4, 5
BTN_CROSS, BTN_OPTIONS = 0, 6


def open_controller():
    pygame.joystick.quit()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        return None
    js = pygame.joystick.Joystick(0)
    js.init()
    print(f"Controller: {js.get_name()} ({js.get_numaxes()} axes, {js.get_numbuttons()} buttons)")
    return js


def trigger(v):
    # SDL reports triggers as -1 (released) .. 1 (pressed).
    return (v + 1.0) / 2.0


def show(js):
    while True:
        pygame.event.pump()
        axes = " ".join(f"{i}:{js.get_axis(i):+.2f}" for i in range(js.get_numaxes()))
        btns = " ".join(str(i) for i in range(js.get_numbuttons()) if js.get_button(i))
        print(f"\raxes {axes}  buttons [{btns}]      ", end="", flush=True)
        time.sleep(0.05)


def connect(host):
    while True:
        try:
            s = socket.create_connection((host, PORT), timeout=3)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"Connected to EV3 at {host}:{PORT}")
            return s
        except OSError as e:
            print(f"EV3 not reachable ({e}); retrying...")
            time.sleep(1)


def drive(js, host):
    sock = connect(host)
    period = 1.0 / RATE_HZ
    last_print = 0.0
    while True:
        t0 = time.monotonic()
        pygame.event.pump()
        if js.get_button(BTN_OPTIONS):
            sock.sendall(b"0 0 0\n")
            print("\nOptions pressed, quitting.")
            return
        l, r, a = mix(
            js.get_axis(AXIS_LX),
            js.get_axis(AXIS_LY),
            js.get_axis(AXIS_RY),
            trigger(js.get_axis(AXIS_R2)),
            stop=bool(js.get_button(BTN_CROSS)),
        )
        try:
            sock.sendall(f"{l} {r} {a}\n".encode("ascii"))
        except OSError:
            print("\nConnection lost.")
            sock.close()
            sock = connect(host)
        if t0 - last_print > 0.2:
            print(f"\rL {l:+4d}  R {r:+4d}  A {a:+4d}   ", end="", flush=True)
            last_print = t0
        time.sleep(max(0.0, period - (time.monotonic() - t0)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host", nargs="?", help="EV3 IP address (shown on the brick's screen)")
    ap.add_argument("--show", action="store_true", help="print raw controller values")
    args = ap.parse_args()
    if not args.show and not args.host:
        ap.error("give the EV3 IP address, or --show")

    pygame.init()
    js = open_controller()
    while js is None:
        print("No controller found. Pair or plug in the DS4...")
        time.sleep(2)
        js = open_controller()

    try:
        show(js) if args.show else drive(js, args.host)
    except KeyboardInterrupt:
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
