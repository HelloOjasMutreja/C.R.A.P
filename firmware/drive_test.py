"""Drive the rover by hand from a laptop, to test motors and calibrate before using the app.

Connect the laptop to the AgriUGV Wi-Fi, raise the wheels, then run:

    python firmware/drive_test.py

Needs only Python. Type a command and press Enter:

    f 50     forward 50 cm          b 50     back 50 cm
    r 90     turn right 90 degrees  l 90     turn left 90 degrees
    s        stop                   t        show the latest sensor reading
    q        quit
"""

import json
import socket
import sys
import threading
import time

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.4.1"
PORT = 3333

latest = {}


def send(link, message):
    link.sendall((json.dumps(message) + "\n").encode())


def heartbeat(link):
    """The ESP32 stops the motors after 1 second of silence."""
    while True:
        send(link, {"cmd": "PING"})
        time.sleep(0.3)


def listen(link):
    for line in link.makefile():
        message = json.loads(line)
        if message.get("type") == "STATUS":
            print("  robot:", message["status"], flush=True)
        else:
            latest.update(message)


def main():
    print(f"Connecting to {HOST}:{PORT} ...")
    link = socket.create_connection((HOST, PORT), timeout=5)
    link.settimeout(None)
    threading.Thread(target=heartbeat, args=(link,), daemon=True).start()
    threading.Thread(target=listen, args=(link,), daemon=True).start()
    print(__doc__.split("Needs only Python.")[1])

    while True:
        words = input("> ").split()
        if not words:
            send(link, {"cmd": "STOP"})
            continue
        command, amount = words[0], float(words[1]) if len(words) > 1 else 0
        if command == "q":
            send(link, {"cmd": "STOP"})
            return
        if command == "s":
            send(link, {"cmd": "STOP"})
        elif command == "t":
            print("  ", latest)
        elif command in ("f", "b"):
            send(link, {"cmd": "MOVE_CM", "distance": amount if command == "f" else -amount, "speed": 120})
        elif command in ("r", "l"):
            send(link, {"cmd": "TURN_DEG", "angle": amount if command == "r" else -amount, "speed": 110})
        else:
            print("  unknown command")


if __name__ == "__main__":
    main()
