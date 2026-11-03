"""Generate printable ArUco plant tags.

    python -m live.make_tags --count 12 --out markers

Print them, tape each one to a stake next to its plant, and the live page
selects the right plant automatically when the tag is in view.
"""

import argparse
from pathlib import Path

import cv2

from .markers import plant_id_for_marker, render_marker


def main():
    parser = argparse.ArgumentParser(description="Generate printable ArUco plant tags.")
    parser.add_argument("--count", type=int, default=12, help="number of tags, starting at --start")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--out", default="markers", help="output folder")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for marker_id in range(args.start, args.start + args.count):
        path = out / f"{plant_id_for_marker(marker_id)}.png"
        cv2.imwrite(str(path), render_marker(marker_id))
        print(f"Saved {path}")


if __name__ == "__main__":
    main()
