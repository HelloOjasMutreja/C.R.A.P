import tempfile
import unittest
from pathlib import Path
import numpy as np

from diagnostics import DiagnosticEngine
from dossier import DossierService, PlantStore
from vision import PlantDocDetector, DossierPerceptionBridge, DetectionResult, DEFAULT_WEIGHTS_PATH


class TestVision(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store_file = Path(self.temp_dir.name) / "plants.json"
        self.service = DossierService(store=PlantStore(file_path=self.store_file))
        self.sample_image = Path(__file__).parent.parent / "sample_images" / "tomato_leaf.png"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_weights_exist(self):
        self.assertTrue(DEFAULT_WEIGHTS_PATH.exists(), f"Missing weights at {DEFAULT_WEIGHTS_PATH}")
        self.assertGreater(DEFAULT_WEIGHTS_PATH.stat().st_size, 10_000_000)

    def test_detector_initialization_and_prediction(self):
        detector = PlantDocDetector()
        self.assertIsNotNone(detector.model)

        detections = detector.predict(self.sample_image, conf=0.25)
        self.assertIsInstance(detections, list)
        self.assertGreater(len(detections), 0)

        first = detections[0]
        self.assertIn("Tomato", first.species)
        self.assertIsInstance(first.confidence, float)
        self.assertGreater(first.confidence, 0.0)
        self.assertEqual(len(first.bbox), 4)

    def test_detector_annotation(self):
        detector = PlantDocDetector()
        output_file = Path(self.temp_dir.name) / "annotated.jpg"

        annotated = detector.annotate(self.sample_image, output_path=output_file)
        self.assertIsInstance(annotated, np.ndarray)
        self.assertTrue(output_file.exists())
        self.assertGreater(output_file.stat().st_size, 0)

    def test_summarize_detections(self):
        detector = PlantDocDetector()
        detections = detector.predict(self.sample_image, conf=0.25)
        summary = detector.summarize(detections)

        self.assertGreater(summary["total_detections"], 0)
        self.assertEqual(summary["species"], "Tomato")
        self.assertIn(summary["overall_status"], ["healthy", "diseased"])

    def test_bridge_end_to_end_logging(self):
        bridge = DossierPerceptionBridge(service=self.service)
        result = bridge.process_image(
            plant_id="PLANT_TOMATO_01",
            image_source=self.sample_image,
            location="Greenhouse_Row_3",
            conf_threshold=0.25,
        )

        plant = result["plant"]
        self.assertEqual(plant.plant_id, "PLANT_TOMATO_01")
        self.assertEqual(plant.location, "Greenhouse_Row_3")
        self.assertEqual(plant.species, "Tomato")

        # The bridge records evidence only; diagnosing is the engine's job.
        self.assertEqual(plant.current_status, "unassessed")
        self.assertEqual(plant.diagnoses, [])

        # Check Observation carries the raw detections
        self.assertEqual(len(plant.observations), 1)
        obs = plant.observations[0]
        self.assertEqual(obs.source, "yolo_plantdoc_pipeline")
        self.assertEqual(len(obs.detections), len(result["detections"]))
        self.assertEqual(obs.detections[0]["species"], "Tomato")
        self.assertEqual(len(obs.detections[0]["bbox"]), 4)

        # Verify persistence across store reload
        reloaded_service = DossierService(store=PlantStore(file_path=self.store_file))
        reloaded_plant = reloaded_service.get_plant("PLANT_TOMATO_01")
        self.assertEqual(len(reloaded_plant.observations), 1)
        self.assertEqual(reloaded_plant.observations[0].detections, obs.detections)

    def test_bridge_and_engine_on_sample_image(self):
        bridge = DossierPerceptionBridge(service=self.service)
        engine = DiagnosticEngine(service=self.service)

        bridge.process_image("PLANT_TOMATO_01", self.sample_image, conf_threshold=0.25)
        result = engine.evaluate("PLANT_TOMATO_01")

        # The sample image contains only healthy tomato leaves.
        self.assertEqual(result.plant_status, "healthy")
        self.assertEqual(result.diagnoses, [])


class FakeDetector:
    """Stands in for YOLO so the diseased path can be tested without a diseased image."""

    def __init__(self, detections):
        self.detections = detections

    def predict(self, source, conf=0.25, iou=0.45):
        return self.detections

    def summarize(self, detections):
        return PlantDocDetector.summarize(detections)


class TestBridgeWithFakeDetector(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        store_file = Path(self.temp_dir.name) / "plants.json"
        self.service = DossierService(store=PlantStore(file_path=store_file))
        self.engine = DiagnosticEngine(service=self.service)
        blight = DetectionResult(
            class_id=18,
            raw_class_name="Tomato Early blight leaf",
            species="Tomato",
            condition="Early Blight",
            is_healthy=False,
            confidence=0.83,
            bbox=(10, 20, 110, 120),
        )
        self.bridge = DossierPerceptionBridge(
            service=self.service,
            detector=FakeDetector([blight]),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_diseased_detection_needs_two_visits_to_confirm(self):
        self.bridge.process_image("PLANT_TOMATO_02", "visit1.jpg")
        first = self.engine.evaluate("PLANT_TOMATO_02")

        self.assertEqual(first.plant_status, "suspected_disease")
        self.assertEqual(first.diagnoses[0].possible_condition, "Tomato Early Blight")
        self.assertEqual(first.diagnoses[0].status, "suspected")

        self.bridge.process_image("PLANT_TOMATO_02", "visit2.jpg")
        second = self.engine.evaluate("PLANT_TOMATO_02")

        self.assertEqual(second.plant_status, "diseased")
        self.assertEqual(second.diagnoses[0].status, "confirmed")

        plant = self.service.get_plant("PLANT_TOMATO_02")
        self.assertEqual(plant.observations[0].detections[0]["bbox"], [10, 20, 110, 120])
        self.assertEqual(plant.observations[0].image_reference, "visit1.jpg")


if __name__ == "__main__":
    unittest.main()
