import unittest

from diagnostics import DiagnosticEngine
from dossier import DossierService, PlantStore
from dossier.models import Action

import tempfile
from datetime import datetime
from pathlib import Path


def detection(condition="Early Blight", view=0, confidence=0.8, healthy=False):
    """``view`` moves the box, so different numbers look like different camera views."""
    return {
        "class_id": 0,
        "raw_class_name": f"Tomato {condition}",
        "species": "Tomato",
        "condition": "Healthy" if healthy else condition,
        "is_healthy": healthy,
        "confidence": confidence,
        "bbox": [view * 40, 0, view * 40 + 30, 30],
    }


class TestDecisionRules(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        store = PlantStore(file_path=Path(self.temp_dir.name) / "plants.json")
        self.service = DossierService(store=store)
        self.engine = DiagnosticEngine(service=self.service)
        self.service.register_plant("P", "A1", species="Tomato")

    def tearDown(self):
        self.temp_dir.cleanup()

    def visit(self, *detections):
        observation = self.service.submit_observation("P", detections=list(detections))
        return self.engine.evaluate("P", observation.observation_id)

    def confirm_disease(self):
        self.visit(detection(view=1))
        return self.visit(detection(view=2))

    def test_one_healthy_view_does_not_clear_a_confirmed_disease(self):
        self.confirm_disease()

        result = self.visit(detection(view=3, healthy=True))

        self.assertEqual(result.plant_status, "diseased")

    def test_repeated_healthy_views_clear_it_gradually(self):
        self.confirm_disease()

        statuses = [
            self.visit(detection(view=v, healthy=True)).plant_status
            for v in (3, 4, 5)
        ]

        self.assertEqual(statuses, ["diseased", "suspected_disease", "healthy"])

    def test_unusable_frame_keeps_the_known_status(self):
        self.confirm_disease()

        result = self.visit()

        self.assertEqual(result.plant_status, "diseased")
        self.assertTrue(any("No Tomato leaves" in n for n in result.notes))

    def test_unusable_first_visit_needs_reinspection(self):
        self.assertEqual(self.visit().plant_status, "needs_reinspection")

    def test_same_view_twice_does_not_confirm(self):
        self.visit(detection(view=1))

        result = self.visit(detection(view=1))

        self.assertEqual(result.plant_status, "suspected_disease")
        self.assertTrue(any("same view" in n for n in result.notes))

    def test_small_camera_shake_counts_as_the_same_view(self):
        self.visit(detection(view=1))
        shaken = detection(view=1, confidence=0.81)
        shaken["bbox"] = [41, 0, 71, 30]

        self.assertEqual(self.visit(shaken).plant_status, "suspected_disease")

    def test_rival_diseases_are_not_both_confirmed(self):
        self.visit(detection("Early Blight", 1), detection("Late Blight", 2))

        result = self.visit(detection("Early Blight", 3), detection("Late Blight", 4))

        self.assertEqual(result.plant_status, "uncertain")
        self.assertFalse(any(d.status == "confirmed" for d in result.diagnoses))
        self.assertTrue(any("Late Blight" in n for n in result.notes))

    def test_clear_leader_beats_a_single_rival_sighting(self):
        self.visit(detection("Early Blight", 1))
        self.visit(detection("Late Blight", 2))

        result = self.visit(detection("Early Blight", 3))

        confirmed = [d.possible_condition for d in result.diagnoses if d.status == "confirmed"]
        self.assertEqual(confirmed, ["Tomato Early Blight"])
        rival = next(d for d in result.diagnoses if "Late" in d.possible_condition)
        self.assertEqual(rival.status, "suspected")

    def test_minority_of_recent_views_does_not_confirm(self):
        self.visit(detection(view=1))
        self.visit(detection(view=2, healthy=True))
        self.visit(detection(view=3, healthy=True))

        result = self.visit(detection(view=4))

        self.assertEqual(result.plant_status, "suspected_disease")

    def test_evidence_reports_the_vote(self):
        self.visit(detection(view=1))
        self.visit(detection(view=2, healthy=True))

        result = self.visit(detection(view=3))

        self.assertTrue(any("2 of 3" in e for e in result.diagnoses[0].supporting_evidence))

    def test_old_observation_does_not_change_current_status(self):
        first = self.service.submit_observation("P", detections=[detection(view=0, healthy=True)])
        self.engine.evaluate("P", first.observation_id)
        self.confirm_disease()

        self.engine.evaluate("P", first.observation_id)

        self.assertEqual(self.service.get_plant("P").current_status, "diseased")

    def test_evidence_before_a_spray_no_longer_counts(self):
        self.confirm_disease()
        plant = self.service.get_plant("P")
        plant.actions.append(Action(
            action_id="ACT_1",
            timestamp=datetime.now(),
            action_type="spray_plant",
            reason="test",
            status="completed",
            completed_at=datetime.now(),
        ))
        self.service.store.save_plants({"P": plant})

        first = self.visit(detection(view=3))
        self.assertEqual(first.plant_status, "suspected_disease")

        self.assertEqual(self.visit(detection(view=4)).plant_status, "diseased")


if __name__ == "__main__":
    unittest.main()
