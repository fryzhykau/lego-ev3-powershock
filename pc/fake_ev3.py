"""Stand-in for DS4Receiver, for testing the PC client without the brick.

    python fake_ev3.py          then in another terminal: python ds4_client.py 127.0.0.1
"""

import socket
import time

PORT = 5000
WATCHDOG_S = 0.5


def main():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT))
    srv.listen(1)
    print(f"fake EV3 listening on {PORT}")
    while True:
        conn, addr = srv.accept()
        print(f"client {addr}")
        conn.settimeout(WATCHDOG_S)
        buf = b""
        n = 0
        while True:
            try:
                data = conn.recv(1024)
            except socket.timeout:
                print("\nwatchdog: no data for 500 ms -> motors stop")
                continue
            if not data:
                break
            buf += data
            *lines, buf = buf.split(b"\n")
            for line in lines:
                n += 1
                if n % 10 == 0:
                    print(f"\r{line.decode():<20}", end="", flush=True)
        print("\nclient disconnected")
        conn.close()


if __name__ == "__main__":
    main()
