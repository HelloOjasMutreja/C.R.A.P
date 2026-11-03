"""ArUco plant tags: a printed marker on a stake tells the camera which plant it is looking at.

Marker id N maps to plant id ``PLANT_{N:03d}`` (marker 7 -> PLANT_007).

Print a sheet of tags with:
    python -m live.make_tags --count 12 --out markers
"""

from typing import Optional

import cv2
import numpy as np

ARUCO_DICTIONARY = cv2.aruco.DICT_4X4_50


def plant_id_for_marker(marker_id: int) -> str:
    return f"PLANT_{marker_id:03d}"


class PlantTagReader:
    """Finds ArUco plant tags in a BGR image."""

    def __init__(self):
        dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICTIONARY)
        self.detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())

    def read(self, image: np.ndarray) -> Optional[dict]:
        """Return the largest visible tag as {"plant_id", "marker_id", "corners"}, or None."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.detector.detectMarkers(gray)
        if ids is None or len(ids) == 0:
            return None

        # The closest (largest) tag is the plant in front of the camera.
        areas = [cv2.contourArea(c.reshape(-1, 2)) for c in corners]
        best = int(np.argmax(areas))
        # OpenCV 4 returns ids as (N, 1), OpenCV 5 as (N,).
        marker_id = int(np.asarray(ids).reshape(-1)[best])

        return {
            "plant_id": plant_id_for_marker(marker_id),
            "marker_id": marker_id,
            "corners": corners[best].reshape(-1, 2).round().astype(int).tolist(),
        }


def render_marker(marker_id: int, size: int = 600) -> np.ndarray:
    """Marker image with a white border and the plant id printed underneath."""
    dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICTIONARY)
    marker = cv2.aruco.generateImageMarker(dictionary, marker_id, size)

    border = size // 8
    canvas = np.full((size + border * 3, size + border * 2), 255, dtype=np.uint8)
    canvas[border:border + size, border:border + size] = marker

    label = plant_id_for_marker(marker_id)
    scale = size / 400
    (tw, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    cv2.putText(
        canvas,
        label,
        ((canvas.shape[1] - tw) // 2, border + size + int(border * 1.6)),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        0,
        2,
        cv2.LINE_AA,
    )
    return canvas

