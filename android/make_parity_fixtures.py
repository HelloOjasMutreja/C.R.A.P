"""Record what the Python decision rules do, so the Kotlin port can be held to it.

    python android/make_parity_fixtures.py

Plays random plant histories through the real engine and action manager, and
writes every outcome to the Kotlin unit test's resources.
"""

import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import dossier.service as service_module  # noqa: E402
from actions import ActionManager  # noqa: E402
from diagnostics import DiagnosticEngine  # noqa: E402
from dossier import DossierService  # noqa: E402
from hardware import SimulatedRobot  # noqa: E402

TARGET = ROOT / "android" / "app" / "src" / "test" / "resources" / "decision_scenarios.json"
SCENARIOS = 400
START = datetime(2026, 1, 1, 8, 0)
CONDITIONS = ["Early Blight", "Late Blight", "Leaf Mold", "Mosaic Virus"]


class Clock:
    now_value = START

    @classmethod
    def now(cls):
        return cls.now_value


class MemoryStore:
    def __init__(self):
        self.plants = {}

    def load_plants(self):
        return dict(self.plants)

    def save_plants(self, plants):
        self.plants = dict(plants)

    def get_plant(self, plant_id):
        return self.plants.get(plant_id)

    def add_plant(self, plant):
        self.plants[plant.plant_id] = plant


def detection(rng, species="Tomato"):
    healthy = rng.random() < 0.35
    condition = "Healthy" if healthy else rng.choice(CONDITIONS)
    x = rng.randrange(0, 300, 10)
    return {
        "raw_class_name": f"{species} {condition}",
        "species": species,
        "condition": condition,
        "is_healthy": healthy,
        "confidence": rng.choice([0.2, 0.3, 0.36, 0.45, 0.55, 0.61, 0.7, 0.82, 0.93]),
        "bbox": [x, 0, x + 60, 60],
    }


def frame(rng, previous, focus):
    """``focus`` holds the diseases this plant keeps showing, so rules that need repeats fire."""
    kind = rng.random()
    if kind < 0.12:
        return []
    if kind < 0.25 and previous:
        return [dict(d) for d in previous]
    found = []
    for _ in range(rng.randint(1, 3)):
        d = detection(rng)
        if focus and rng.random() < 0.8:
            condition = rng.choice(focus)
            d["condition"] = condition
            d["raw_class_name"] = f"Tomato {condition}"
            d["is_healthy"] = False
            d["confidence"] = rng.choice([0.45, 0.61, 0.7, 0.82, 0.93])
        found.append(d)
    if rng.random() < 0.15:
        found.append(detection(rng, "Potato"))
    return found


def play(rng):
    sequence = {"n": 0}

    def new_id(prefix):
        sequence["n"] += 1
        return f"{prefix}_{sequence['n']}"

    DossierService._new_id = staticmethod(new_id)
    Clock.now_value = START

    species = "Tomato" if rng.random() < 0.8 else None
    fail_on = rng.choice([[], [], [], ["inspect"], ["spray_trigger"], ["forward"]])
    has_arm = rng.random() < 0.85

    service = DossierService(store=MemoryStore())
    engine = DiagnosticEngine(service=service)
    robot = SimulatedRobot(fail_on=set(fail_on))
    robot.has_arm = has_arm
    manager = ActionManager(service=service, robot=robot, clock=Clock.now)
    service.register_plant("P", "A1", species=species)

    focus = rng.choice([[], [CONDITIONS[0]], [CONDITIONS[1]], CONDITIONS[:2], CONDITIONS[1:3]])

    steps = []
    previous = []
    for _ in range(rng.randint(3, 12)):
        hours = rng.choice([1, 2, 6, 24, 40, 80])
        Clock.now_value += timedelta(hours=hours)
        detections = frame(rng, previous, focus)
        previous = detections or previous
        humidity = rng.choice([None, None, 45.0, 72.0, 88.0])
        image = rng.choice([None, None, None, "a.jpg", "b.jpg"])
        op = rng.choice(["run", "run", "run", "reject", "leave"])

        readings = {} if humidity is None else {"humidity_rh": humidity}
        observation = service.submit_observation(
            "P", image_reference=image, sensor_readings=readings, detections=detections
        )
        result = engine.evaluate("P", observation.observation_id)
        manager.link_verification("P", observation.observation_id)
        action = manager.propose("P")

        if action is not None and op == "reject":
            manager.reject("P", action.action_id)
        elif action is not None and op == "run":
            if action.status == "awaiting_approval":
                manager.approve("P", action.action_id)
            manager.execute("P", action.action_id)

        plant = service.get_plant("P")
        steps.append({
            "hours": hours,
            "detections": detections,
            "humidity": humidity,
            "image": image,
            "op": op,
            "status": result.plant_status,
            "plant_status": plant.current_status,
            "notes": result.notes,
            "diagnoses": [
                {
                    "condition": d.possible_condition,
                    "status": d.status,
                    "confidence": d.confidence,
                    "supporting": d.supporting_evidence,
                    "contradicting": d.contradicting_evidence,
                    "observations": d.observation_ids,
                }
                for d in result.diagnoses
            ],
            "actions": [
                {
                    "id": a.action_id,
                    "type": a.action_type,
                    "status": a.status,
                    "reason": a.reason,
                    "result": a.result,
                    "verification": a.verification_observation_id,
                }
                for a in plant.actions
            ],
            "robot": [" ".join(str(part) for part in entry) for entry in robot.log],
        })

    return {"species": species, "fail_on": fail_on, "has_arm": has_arm, "steps": steps}


def main():
    service_module.datetime = Clock
    rng = random.Random(2026)
    scenarios = [play(rng) for _ in range(SCENARIOS)]

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(scenarios, ensure_ascii=False), encoding="utf-8")

    steps = [s for scenario in scenarios for s in scenario["steps"]]
    seen = {}
    for s in steps:
        seen[s["status"]] = seen.get(s["status"], 0) + 1
    types = {}
    for scenario in scenarios:
        for a in scenario["steps"][-1]["actions"]:
            key = f"{a['type']}/{a['status']}"
            types[key] = types.get(key, 0) + 1
    print(len(scenarios), "scenarios,", len(steps), "visits,", round(TARGET.stat().st_size / 1e6, 2), "MB")
    print("statuses", seen)
    print("actions", types)


if __name__ == "__main__":
    main()
