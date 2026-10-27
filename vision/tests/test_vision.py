import tempfile
import unittest
from pathlib import Path
import numpy as np

from dossier import DossierService, PlantStore
from vision import PlantDocDetector, DossierPerceptionBridge, DEFAULT_WEIGHTS_PATH


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
        self.assertIn(plant.current_status, ["healthy", "diseased"])

        # Check Observation
        self.assertEqual(len(plant.observations), 1)
        obs = plant.observations[0]
        self.assertEqual(obs.source, "yolo_plantdoc_pipeline")
        self.assertGreater(len(obs.visual_symptoms), 0)

        # Check Diagnoses
        self.assertGreater(len(plant.diagnoses), 0)
        diag = plant.diagnoses[0]
        self.assertIsNotNone(diag.confidence)
        self.assertGreater(len(diag.supporting_evidence), 0)

        # Verify persistence across store reload
        reloaded_service = DossierService(store=PlantStore(file_path=self.store_file))
        reloaded_plant = reloaded_service.get_plant("PLANT_TOMATO_01")
        self.assertEqual(len(reloaded_plant.observations), 1)
        self.assertEqual(len(reloaded_plant.diagnoses), len(plant.diagnoses))
        self.assertEqual(reloaded_plant.current_status, plant.current_status)


if __name__ == "__main__":
    unittest.main()
