import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient

from dossier import DossierService, PlantStore
from live import PlantTagReader, create_app, plant_id_for_marker, render_marker
from live.certs import ensure_certificate
from vision import DetectionResult, PlantDocDetector


def jpeg(image):
    ok, buffer = cv2.imencode(".jpg", image)
    assert ok
    return buffer.tobytes()


def blank_frame(width=320, height=240):
    return np.full((height, width, 3), 90, dtype=np.uint8)


class FakeDetector:
    """Stands in for YOLO: always sees one early-blight tomato leaf and one healthy one."""

    def __init__(self):
        self.calls = 0

    def predict(self, source, conf=0.25, iou=0.45):
        self.calls += 1
        return [
            DetectionResult(18, "Tomato Early blight leaf", "Tomato", "Early Blight", False, 0.82, (10, 10, 60, 60)),
            DetectionResult(20, "Tomato leaf", "Tomato", "Healthy", True, 0.9, (70, 20, 120, 80)),
        ]

    def summarize(self, detections):
        return PlantDocDetector.summarize(detections)


class TestLiveServer(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.service = DossierService(store=PlantStore(file_path=root / "plants.json"))
        self.detector = FakeDetector()
        self.images_dir = root / "images"
        self.client = TestClient(
            create_app(self.detector, service=self.service, images_dir=self.images_dir)
        )

    def tearDown(self):
        self.client.close()
        self.temp_dir.cleanup()

    def test_index_page_is_served(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("C.R.A.P Live", response.text)
        self.assertEqual(self.client.get("/static/app.js").status_code, 200)

    def test_live_frame_returns_detections(self):
        with self.client.websocket_connect("/ws/detect") as ws:
            ws.send_bytes(jpeg(blank_frame()))
            result = ws.receive_json()

        self.assertEqual(result["type"], "detections")
        self.assertEqual((result["width"], result["height"]), (320, 240))
        self.assertEqual(len(result["detections"]), 2)
        self.assertEqual(result["detections"][0]["condition"], "Early Blight")
        self.assertEqual(result["detections"][0]["bbox"], [10, 10, 60, 60])
        self.assertIsNone(result["tag"])

    def test_live_frames_do_not_touch_the_dossier(self):
        with self.client.websocket_connect("/ws/detect") as ws:
            for _ in range(3):
                ws.send_bytes(jpeg(blank_frame()))
                ws.receive_json()

        self.assertEqual(self.service.list_plants(), [])

    def test_bad_frame_reports_error_and_keeps_connection(self):
        with self.client.websocket_connect("/ws/detect") as ws:
            ws.send_bytes(b"not a jpeg")
            self.assertEqual(ws.receive_json()["type"], "error")

            ws.send_bytes(jpeg(blank_frame()))
            self.assertEqual(ws.receive_json()["type"], "detections")

    def test_live_frame_reads_plant_tag(self):
        frame = np.full((480, 640, 3), 255, dtype=np.uint8)
        marker = cv2.cvtColor(render_marker(7, size=200), cv2.COLOR_GRAY2BGR)
        frame[100:100 + marker.shape[0], 200:200 + marker.shape[1]] = marker

        with self.client.websocket_connect("/ws/detect") as ws:
            ws.send_bytes(jpeg(frame))
            result = ws.receive_json()

        self.assertEqual(result["tag"]["plant_id"], "PLANT_007")
        self.assertEqual(len(result["tag"]["corners"]), 4)

    def test_record_visit_saves_image_and_evaluates(self):
        response = self.client.post(
            "/api/plants/plant_001/visits?location=Bed%20A1",
            content=jpeg(blank_frame()),
            headers={"Content-Type": "image/jpeg"},
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["status"], "suspected_disease")
        self.assertEqual(result["new_diagnoses"][0]["condition"], "Tomato Early Blight")
        self.assertEqual(result["new_diagnoses"][0]["status"], "suspected")
        self.assertEqual(result["plant"]["plant_id"], "PLANT_001")
        self.assertEqual(result["plant"]["location"], "Bed A1")
        self.assertEqual(result["plant"]["visits"], 1)
        self.assertTrue((self.images_dir / result["image"]).exists())

        plant = self.service.get_plant("PLANT_001")
        self.assertEqual(plant.observations[0].image_reference, str(self.images_dir / result["image"]))

    def test_second_visit_confirms(self):
        for _ in range(2):
            response = self.client.post(
                "/api/plants/PLANT_001/visits",
                content=jpeg(blank_frame()),
                headers={"Content-Type": "image/jpeg"},
            )

        result = response.json()
        self.assertEqual(result["status"], "diseased")
        self.assertEqual(result["new_diagnoses"][0]["status"], "confirmed")
        self.assertEqual(result["plant"]["visits"], 2)

    def test_record_rejects_non_image(self):
        response = self.client.post("/api/plants/PLANT_001/visits", content=b"nope")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.service.list_plants(), [])

    def test_plant_endpoints(self):
        self.assertEqual(self.client.get("/api/plants").json(), [])
        self.assertEqual(self.client.get("/api/plants/PLANT_404").status_code, 404)

        self.service.register_plant("PLANT_002", "Bed B2", species="Tomato")

        plants = self.client.get("/api/plants").json()
        self.assertEqual([p["plant_id"] for p in plants], ["PLANT_002"])
        summary = self.client.get("/api/plants/PLANT_002").json()
        self.assertEqual(summary["status"], "unassessed")
        self.assertEqual(summary["visits"], 0)
        self.assertIsNone(summary["last_visit"])


class TestMarkersAndCerts(unittest.TestCase):

    def test_marker_ids_map_to_plant_ids(self):
        self.assertEqual(plant_id_for_marker(7), "PLANT_007")
        self.assertEqual(plant_id_for_marker(42), "PLANT_042")

    def test_reader_returns_none_without_tag(self):
        self.assertIsNone(PlantTagReader().read(blank_frame()))

    def test_certificate_is_created_once_and_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            cert, key = ensure_certificate(Path(temp), ["192.168.1.20"])
            self.assertTrue(cert.exists() and key.exists())
            first = cert.read_bytes()

            ensure_certificate(Path(temp), ["192.168.1.20"])
            self.assertEqual(cert.read_bytes(), first)

            # A new network address needs a new certificate.
            ensure_certificate(Path(temp), ["10.0.0.5"])
            self.assertNotEqual(cert.read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
