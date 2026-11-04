import tempfile
import unittest
from pathlib import Path

from datetime import datetime, timedelta

from actions import MAX_REPEATS, SPRAY_COOLDOWN, ActionManager
from diagnostics import DiagnosticEngine
from dossier import DossierService, PlantStore
from hardware import RobotError, SimulatedRobot


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


class NoArmRobot(SimulatedRobot):
    """Like the real robot today: wheels only, arm steps are refused."""

    has_arm = False

    def arm(self, pose):
        raise RobotError("no arm")


class TestActionManager(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store_file = Path(self.temp_dir.name) / "plants.json"
        self.service = DossierService(store=PlantStore(file_path=self.store_file))
        self.engine = DiagnosticEngine(service=self.service)
        self.robot = SimulatedRobot()
        self.manager = ActionManager(service=self.service, robot=self.robot)
        self.service.register_plant("PLANT001", "A1", species="Tomato")
        self.view = 0

    def tearDown(self):
        self.temp_dir.cleanup()

    def visit(self, *detections):
        # Each visit is a different camera view, as the engine requires.
        self.view += 1
        detections = [d | {"bbox": [self.view * 40, 0, self.view * 40 + 30, 30]} for d in detections]
        obs = self.service.submit_observation("PLANT001", detections=detections)
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

        # The repeat sighting confirms the disease, so the next step is spraying.
        self.assertEqual(self.service.get_plant("PLANT001").current_status, "diseased")
        self.assertEqual(self.manager.propose("PLANT001").action_type, "spray_plant")

    def test_spraying_needs_approval(self):
        self.visit(detection())
        self.visit(detection())
        action = self.manager.propose("PLANT001")

        self.assertEqual(action.action_type, "spray_plant")
        self.assertEqual(action.status, "awaiting_approval")
        with self.assertRaises(ValueError):
            self.manager.execute("PLANT001", action.action_id)
        self.assertEqual(self.robot.log, [])

        self.manager.approve("PLANT001", action.action_id)
        done = self.manager.execute("PLANT001", action.action_id)

        self.assertEqual(done.status, "completed")
        self.assertEqual(self.robot.log, [("arm", "spray"), ("spray", 500), ("arm", "home")])

    def test_robot_failure_stops_and_records(self):
        manager = ActionManager(service=self.service, robot=SimulatedRobot(fail_on={"forward"}))
        self.visit(detection(healthy=True))
        action = manager.propose("PLANT001")

        failed = manager.execute("PLANT001", action.action_id)

        self.assertEqual(failed.status, "failed")
        self.assertIn("arm → home", failed.result)
        self.assertIn("Simulated failure", failed.result)
        self.assertEqual(manager.robot.log[-1], ("drive", "stop", 0))

    def test_robot_without_arm_still_moves_on(self):
        robot = NoArmRobot()
        manager = ActionManager(service=self.service, robot=robot)
        self.visit(detection(healthy=True))
        action = manager.propose("PLANT001")

        done = manager.execute("PLANT001", action.action_id)

        self.assertEqual(done.status, "completed")
        self.assertEqual(robot.log, [("drive", "forward", 1000)])

    def test_robot_without_arm_fails_inspection_honestly(self):
        manager = ActionManager(service=self.service, robot=NoArmRobot())
        self.visit(detection())
        action = manager.propose("PLANT001")

        failed = manager.execute("PLANT001", action.action_id)

        self.assertEqual(failed.status, "failed")
        self.assertIn("no arm", failed.result)

    def test_one_open_action_per_plant(self):
        self.visit(detection())
        first = self.manager.propose("PLANT001")
        again = self.manager.propose("PLANT001")
        self.assertEqual(first.action_id, again.action_id)

        self.visit(detection(healthy=True))
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

    def spray_confirmed_plant(self, manager=None):
        manager = manager or self.manager
        self.visit(detection())
        self.visit(detection())
        action = manager.propose("PLANT001")
        manager.approve("PLANT001", action.action_id)
        return manager.execute("PLANT001", action.action_id)

    def test_no_repeat_spray_during_cooldown(self):
        self.spray_confirmed_plant()
        self.visit(detection())
        self.visit(detection())

        action = self.manager.propose("PLANT001")

        self.assertEqual(self.service.get_plant("PLANT001").current_status, "diseased")
        self.assertEqual(action.action_type, "move_on")
        self.assertIn("sprayed", action.reason)

    def test_disease_after_cooldown_goes_to_a_person(self):
        now = [datetime(2026, 11, 1, 9, 0)]
        manager = ActionManager(service=self.service, robot=self.robot, clock=lambda: now[0])
        self.spray_confirmed_plant(manager)
        now[0] += SPRAY_COOLDOWN + timedelta(hours=1)
        self.visit(detection())
        self.visit(detection())

        action = manager.propose("PLANT001")

        self.assertEqual(action.action_type, "request_review")
        self.assertIn("after treatment", action.reason)

    def test_spray_records_when_it_finished(self):
        done = self.spray_confirmed_plant()

        self.assertIsNotNone(done.completed_at)

    def test_inspections_stop_and_ask_a_person(self):
        types = []
        for _ in range(MAX_REPEATS + 1):
            self.visit(detection(confidence=0.5))
            action = self.manager.propose("PLANT001")
            types.append(action.action_type)
            self.manager.execute("PLANT001", action.action_id)

        self.assertEqual(types, ["inspect_closer"] * MAX_REPEATS + ["request_review"])

    def test_retries_stop_and_ask_a_person(self):
        types = []
        for _ in range(MAX_REPEATS + 1):
            self.visit()
            action = self.manager.propose("PLANT001")
            types.append(action.action_type)
            self.manager.execute("PLANT001", action.action_id)

        self.assertEqual(types, ["reposition_and_retry"] * MAX_REPEATS + ["request_review"])

    def test_conflicting_diseases_go_to_a_person_without_moving_the_robot(self):
        self.visit(detection("Early Blight"), detection("Late Blight"))
        self.visit(detection("Early Blight"), detection("Late Blight"))

        action = self.manager.propose("PLANT001")
        done = self.manager.execute("PLANT001", action.action_id)

        self.assertEqual(action.action_type, "request_review")
        self.assertIn("Early Blight", action.reason)
        self.assertEqual(done.status, "completed")
        self.assertEqual(self.robot.log, [])

    def test_unknown_action(self):
        with self.assertRaises(ValueError):
            self.manager.execute("PLANT001", "ACT_missing")


if __name__ == "__main__":
    unittest.main()
