import tempfile
import unittest
from pathlib import Path

from actions import ActionManager
from diagnostics import DiagnosticEngine
from dossier import DossierService, PlantStore
from hardware import SimulatedRobot


def detection(condition="Early Blight", confidence=0.8, healthy=False):
    return {
        "class_id": 0,
        "raw_class_name": f"Tomato {condition}",
        "species": "Tomato",
        "condition": "Healthy" if healthy else condition,
        "is_healthy": healthy,
        "confidence": confidence,
        "bbox": [0, 0, 10, 10],
    }


class TestActionManager(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store_file = Path(self.temp_dir.name) / "plants.json"
        self.service = DossierService(store=PlantStore(file_path=self.store_file))
        self.engine = DiagnosticEngine(service=self.service)
        self.robot = SimulatedRobot()
        self.manager = ActionManager(service=self.service, robot=self.robot)
        self.service.register_plant("PLANT001", "A1", species="Tomato")

    def tearDown(self):
        self.temp_dir.cleanup()

    def visit(self, *detections):
        obs = self.service.submit_observation("PLANT001", detections=list(detections))
        self.engine.evaluate("PLANT001", obs.observation_id)
        return obs

    def test_unassessed_plant_gets_no_action(self):
        self.assertIsNone(self.manager.propose("PLANT001"))

    def test_suspected_disease_proposes_closer_inspection(self):
        self.visit(detection(confidence=0.8))

        action = self.manager.propose("PLANT001")

        self.assertEqual(action.action_type, "inspect_closer")
        self.assertEqual(action.status, "proposed")
        self.assertIn("Tomato Early Blight (80%)", action.reason)
        self.assertEqual(self.robot.log, [], "proposing must not move the robot")

    def test_status_to_action_mapping(self):
        cases = [
            ((detection(healthy=True),), "move_on"),
            ((), "reposition_and_retry"),
        ]
        for detections, expected in cases:
            with self.subTest(expected=expected):
                self.visit(*detections)
                self.assertEqual(self.manager.propose("PLANT001").action_type, expected)

    def test_execute_runs_plan_and_records_result(self):
        self.visit(detection())
        action = self.manager.propose("PLANT001")

        done = self.manager.execute("PLANT001", action.action_id)

        self.assertEqual(done.status, "completed")
        self.assertEqual(self.robot.log, [("arm", "inspect")])
        self.assertIn("arm → inspect", done.result)
        self.assertIn("Record a visit to verify", done.result)

    def test_next_visit_verifies_inspection(self):
        self.visit(detection())
        action = self.manager.propose("PLANT001")
        self.manager.execute("PLANT001", action.action_id)

        obs = self.visit(detection(confidence=0.85))
        linked = self.manager.link_verification("PLANT001", obs.observation_id)

        self.assertEqual([a.action_id for a in linked], [action.action_id])
        saved = self.service.get_action("PLANT001", action.action_id)
        self.assertEqual(saved.verification_observation_id, obs.observation_id)
        self.assertIn(f"Verified by {obs.observation_id}", saved.result)
        self.assertNotIn("Record a visit", saved.result)

        # The repeat sighting confirms the disease, so the next step is flagging.
        self.assertEqual(self.service.get_plant("PLANT001").current_status, "diseased")
        self.assertEqual(self.manager.propose("PLANT001").action_type, "flag_plant")

    def test_flagging_needs_approval(self):
        self.visit(detection())
        self.visit(detection())
        action = self.manager.propose("PLANT001")

        self.assertEqual(action.action_type, "flag_plant")
        self.assertEqual(action.status, "awaiting_approval")
        with self.assertRaises(ValueError):
            self.manager.execute("PLANT001", action.action_id)
        self.assertEqual(self.robot.log, [])

        self.manager.approve("PLANT001", action.action_id)
        done = self.manager.execute("PLANT001", action.action_id)

        self.assertEqual(done.status, "completed")
        self.assertEqual(self.robot.log, [("arm", "flag"), ("arm", "home")])

    def test_robot_failure_stops_and_records(self):
        manager = ActionManager(service=self.service, robot=SimulatedRobot(fail_on={"forward"}))
        self.visit(detection(healthy=True))
        action = manager.propose("PLANT001")

        failed = manager.execute("PLANT001", action.action_id)

        self.assertEqual(failed.status, "failed")
        self.assertIn("arm → home", failed.result)
        self.assertIn("Simulated failure", failed.result)
        self.assertEqual(manager.robot.log[-1], ("drive", "stop", 0))

    def test_one_open_action_per_plant(self):
        self.visit(detection())
        first = self.manager.propose("PLANT001")
        again = self.manager.propose("PLANT001")
        self.assertEqual(first.action_id, again.action_id)

        self.visit(detection(healthy=True))
        replacement = self.manager.propose("PLANT001")

        self.assertEqual(replacement.action_type, "move_on")
        old = self.service.get_action("PLANT001", first.action_id)
        self.assertEqual(old.status, "superseded")

    def test_completed_action_cannot_run_twice(self):
        self.visit(detection())
        action = self.manager.propose("PLANT001")
        self.manager.execute("PLANT001", action.action_id)

        with self.assertRaises(ValueError):
            self.manager.execute("PLANT001", action.action_id)
        self.assertEqual(len(self.robot.log), 1)

    def test_reject(self):
        self.visit(detection())
        action = self.manager.propose("PLANT001")

        rejected = self.manager.reject("PLANT001", action.action_id)

        self.assertEqual(rejected.status, "rejected")
        with self.assertRaises(ValueError):
            self.manager.reject("PLANT001", action.action_id)

    def test_actions_survive_reload(self):
        self.visit(detection())
        action = self.manager.propose("PLANT001")
        self.manager.execute("PLANT001", action.action_id)

        reloaded = DossierService(store=PlantStore(file_path=self.store_file))
        saved = reloaded.get_action("PLANT001", action.action_id)

        self.assertEqual(saved.status, "completed")
        self.assertEqual(saved.action_type, "inspect_closer")

    def test_unknown_action(self):
        with self.assertRaises(ValueError):
            self.manager.execute("PLANT001", "ACT_missing")


if __name__ == "__main__":
    unittest.main()
