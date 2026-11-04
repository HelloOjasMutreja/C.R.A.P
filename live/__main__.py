"""Start the live phone feed.

    python -m live

Then open the printed https:// address on your phone (same Wi-Fi or hotspot),
accept the certificate warning once, and allow the camera.
"""

import argparse
from pathlib import Path

CERT_DIR = Path(__file__).parent / "certs"


def main():
    parser = argparse.ArgumentParser(description="C.R.A.P live phone feed")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--conf", type=float, default=0.35, help="detection confidence threshold")
    parser.add_argument("--weights", default=None, help="YOLO weights (defaults to vision/weights/best.pt)")
    parser.add_argument(
        "--no-https",
        action="store_true",
        help="serve plain HTTP; the camera then only works on this laptop at http://localhost",
    )
    parser.add_argument("--bt-port", default=None, help="COM port of the paired ESP32, e.g. COM5")
    parser.add_argument(
        "--has-arm",
        action="store_true",
        help="send arm and spray commands; only use once the firmware supports them",
    )
    args = parser.parse_args()

    import uvicorn

    from hardware import BluetoothRobot, SimulatedRobot
    from vision import PlantDocDetector
    from .certs import ensure_certificate, lan_addresses
    from .server import create_app

    if args.bt_port:
        robot = BluetoothRobot(args.bt_port, has_arm=args.has_arm)
        print(f"Robot: Bluetooth on {args.bt_port}, arm commands {'on' if args.has_arm else 'off'}")
    else:
        robot = SimulatedRobot()
        print("Robot: simulated (pass --bt-port to use the ESP32)")

    print("Loading YOLO model...")
    app = create_app(PlantDocDetector(args.weights), conf=args.conf, robot=robot)

    if args.no_https:
        print(f"\nOpen http://localhost:{args.port} on this laptop.")
        print("Phones need HTTPS for the camera; run without --no-https for them.\n")
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
        return

    addresses = lan_addresses()
    cert, key = ensure_certificate(CERT_DIR, addresses)

    print("\nOpen one of these on your phone (same Wi-Fi or hotspot as this laptop):")
    for ip in addresses or ["<this laptop's IP>"]:
        print(f"    https://{ip}:{args.port}")
    print(f"On this laptop: https://localhost:{args.port}")
    print("The phone will warn about the certificate once: tap Advanced -> Proceed.\n")

    uvicorn.run(app, host="0.0.0.0", port=args.port, ssl_certfile=str(cert), ssl_keyfile=str(key), log_level="warning")


if __name__ == "__main__":
    main()
