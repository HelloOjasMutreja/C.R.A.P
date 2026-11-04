import tempfile
import unittest
from pathlib import Path

from diagnostics import DiagnosticEngine
from dossier import DossierService, PlantStore


def detection(condition="Early Blight", confidence=0.8, species="Tomato", healthy=False):
    return {
        "class_id": 0,
        "raw_class_name": f"{species} {condition}",
        "species": species,
        "condition": "Healthy" if healthy else condition,
        "is_healthy": healthy,
        "confidence": confidence,
        "bbox": [0, 0, 10, 10],
    }


class TestDiagnosticEngine(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store_file = Path(self.temp_dir.name) / "plants.json"
        self.service = DossierService(store=PlantStore(file_path=self.store_file))
        self.engine = DiagnosticEngine(service=self.service)
        self.service.register_plant("PLANT001", "A1", species="Tomato")

    def tearDown(self):
        self.temp_dir.cleanup()

    def observe(self, *detections):
        return self.service.submit_observation(
            plant_id="PLANT001",
            source="test",
            detections=list(detections),
        )

    def test_single_observation_is_only_suspected(self):
        obs = self.observe(detection(confidence=0.95))

        result = self.engine.evaluate("PLANT001")

        self.assertEqual(result.plant_status, "suspected_disease")
        self.assertEqual(len(result.diagnoses), 1)
        diagnosis = result.diagnoses[0]
        self.assertEqual(diagnosis.possible_condition, "Tomato Early Blight")
        self.assertEqual(diagnosis.status, "suspected")
        self.assertEqual(diagnosis.confidence, 0.95)
        self.assertEqual(diagnosis.observation_ids, [obs.observation_id])
        self.assertTrue(
            any("repeat observation" in e for e in diagnosis.supporting_evidence)
        )

    def test_repeat_observation_confirms(self):
        first = self.observe(detection(confidence=0.8))
        self.engine.evaluate("PLANT001")
        second = self.observe(detection(confidence=0.7))

        result = self.engine.evaluate("PLANT001")

        self.assertEqual(result.plant_status, "diseased")
        diagnosis = result.diagnoses[0]
        self.assertEqual(diagnosis.status, "confirmed")
        self.assertEqual(
            diagnosis.observation_ids,
            [second.observation_id, first.observation_id],
        )

    def test_weak_earlier_sighting_does_not_confirm(self):
        self.observe(detection(confidence=0.45))
        self.observe(detection(confidence=0.9))

        result = self.engine.evaluate("PLANT001")

        self.assertEqual(result.diagnoses[0].status, "suspected")
        self.assertEqual(result.plant_status, "suspected_disease")

    def test_weak_current_sighting_does_not_confirm(self):
        self.observe(detection(confidence=0.9))
        self.observe(detection(confidence=0.45))

        result = self.engine.evaluate("PLANT001")

        self.assertEqual(result.diagnoses[0].status, "suspected")

    def test_healthy_leaves_only(self):
        self.observe(detection(healthy=True, confidence=0.9))

        result = self.engine.evaluate("PLANT001")

        self.assertEqual(result.plant_status, "healthy")
        self.assertEqual(result.diagnoses, [])
        self.assertEqual(self.service.get_plant("PLANT001").current_status, "healthy")

    def test_no_detections_needs_reinspection(self):
        self.observe()

        result = self.engine.evaluate("PLANT001")

        self.assertEqual(result.plant_status, "needs_reinspection")
        self.assertEqual(result.diagnoses, [])

    def test_low_confidence_detections_are_ignored(self):
        self.observe(detection(confidence=0.2))

        result = self.engine.evaluate("PLANT001")

        self.assertEqual(result.plant_status, "needs_reinspection")

    def test_other_species_are_ignored(self):
        self.observe(
            detection(condition="Late Blight", species="Potato", confidence=0.9),
            detection(healthy=True, confidence=0.8),
        )

        result = self.engine.evaluate("PLANT001")

        self.assertEqual(result.plant_status, "healthy")
        self.assertEqual(result.diagnoses, [])
        self.assertTrue(any("other species" in n for n in result.notes))

    def test_healthy_leaves_and_misses_are_contradicting_evidence(self):
        earlier = self.observe(detection(healthy=True, confidence=0.9))
        self.observe(
            detection(confidence=0.8),
            detection(healthy=True, confidence=0.9),
        )

        result = self.engine.evaluate("PLANT001")

        contradicting = result.diagnoses[0].contradicting_evidence
        self.assertTrue(any("1 healthy Tomato" in e for e in contradicting))
        self.assertTrue(any(earlier.observation_id in e for e in contradicting))

    def test_conditions_are_diagnosed_separately(self):
        self.observe(
            detection(condition="Early Blight", confidence=0.8),
            detection(condition="Leaf Mold", confidence=0.6),
        )

        result = self.engine.evaluate("PLANT001")

        conditions = sorted(d.possible_condition for d in result.diagnoses)
        self.assertEqual(conditions, ["Tomato Early Blight", "Tomato Leaf Mold"])

    def test_species_taken_from_detections_when_unknown(self):
        self.service.register_plant("PLANT002", "A2")
        self.service.submit_observation(
            plant_id="PLANT002",
            detections=[detection(condition="Common Rust", species="Corn")],
        )

        result = self.engine.evaluate("PLANT002")

        self.assertEqual(result.diagnoses[0].possible_condition, "Corn Common Rust")

    def observe_humidity(self, humidity, *detections):
        return self.service.submit_observation(
            plant_id="PLANT001",
            sensor_readings={"temperature_c": 28.0, "humidity_rh": humidity},
            detections=list(detections),
        )

    def test_high_humidity_supports_but_does_not_confirm(self):
        self.observe_humidity(85.0, detection(condition="Late Blight", confidence=0.95))

        result = self.engine.evaluate("PLANT001")

        diagnosis = result.diagnoses[0]
        self.assertEqual(diagnosis.status, "suspected")
        self.assertTrue(any("85%" in e for e in diagnosis.supporting_evidence))

    def test_low_humidity_adds_nothing(self):
        self.observe_humidity(40.0, detection(condition="Late Blight"))

        result = self.engine.evaluate("PLANT001")

        self.assertFalse(any("humidity" in e for e in result.diagnoses[0].supporting_evidence))

    def test_humidity_ignored_for_unrelated_conditions(self):
        self.observe_humidity(90.0, detection(condition="Mosaic Virus"))

        result = self.engine.evaluate("PLANT001")

        self.assertFalse(any("humidity" in e for e in result.diagnoses[0].supporting_evidence))

    def test_humidity_alone_creates_no_diagnosis(self):
        self.observe_humidity(95.0, detection(healthy=True))

        result = self.engine.evaluate("PLANT001")

        self.assertEqual(result.diagnoses, [])
        self.assertEqual(result.plant_status, "healthy")

    def test_reevaluating_does_not_duplicate(self):
        self.observe(detection())

        first = self.engine.evaluate("PLANT001")
        second = self.engine.evaluate("PLANT001")

        self.assertEqual(
            [d.diagnosis_id for d in first.diagnoses],
            [d.diagnosis_id for d in second.diagnoses],
        )
        self.assertEqual(len(self.service.get_plant("PLANT001").diagnoses), 1)

    def test_evaluate_specific_observation(self):
        first = self.observe(detection())
        self.observe(detection(healthy=True))

        result = self.engine.evaluate("PLANT001", observation_id=first.observation_id)

        self.assertEqual(result.observation_id, first.observation_id)
        self.assertEqual(len(result.diagnoses), 1)

    def test_unknown_observation_is_rejected(self):
        self.observe(detection())

        with self.assertRaises(ValueError):
            self.engine.evaluate("PLANT001", observation_id="OBS_missing")

    def test_no_observations(self):
        result = self.engine.evaluate("PLANT001")

        self.assertIsNone(result.observation_id)
        self.assertEqual(result.plant_status, "unassessed")

    def test_results_survive_reload(self):
        obs = self.observe(detection())
        self.engine.evaluate("PLANT001")

        reloaded = DossierService(store=PlantStore(file_path=self.store_file))
        plant = reloaded.get_plant("PLANT001")

        self.assertEqual(plant.current_status, "suspected_disease")
        self.assertEqual(plant.diagnoses[0].observation_ids, [obs.observation_id])
        self.assertEqual(plant.observations[0].detections[0]["condition"], "Early Blight")


if __name__ == "__main__":
    unittest.main()
