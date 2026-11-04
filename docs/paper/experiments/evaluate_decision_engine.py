"""Compare the current decision engine with the rule described in the paper.

Run from the repository root, after run_experiments.py:
    python docs/paper/experiments/evaluate_decision_engine.py

Both engines see the same simulated plants, built from real detections. The
threshold stays at 0.60 for both, so nothing is tuned on these test images.
Rates count what would have reached the action manager at any visit.
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from legacy_engine import DiagnosticEngine as LegacyEngine  # noqa: E402
from run_experiments import RESULTS, MemoryStore, image_pools  # noqa: E402

from diagnostics import DiagnosticEngine  # noqa: E402
from dossier import DossierService  # noqa: E402

BOOTSTRAPS = 200
PLANTS = 150
TRIALS = 3000


def moved(record, shift, jitter=0.0):
    """The same detections from a shifted camera: a new view with the same mistake."""
    return record | {"detections": [
        d | {
            "bbox": [d["bbox"][0] + shift, d["bbox"][1], d["bbox"][2] + shift, d["bbox"][3]],
            "confidence": min(0.99, max(0.0, d["confidence"] + jitter)),
        }
        for d in record["detections"]
    ]}


def visits_for(pool, count, rng, repeat=0.0, mode="exact"):
    """Different images while the pool lasts; with probability ``repeat`` keep the last view."""
    order = rng.sample(pool, min(count, len(pool)))
    sequence = [order[0]]
    remaining = order[1:]
    step = 0
    while len(sequence) < count:
        step += 1
        if rng.random() < repeat or not remaining:
            previous = sequence[-1]
            if mode == "exact" and remaining:
                sequence.append(previous)
            else:
                sequence.append(moved(previous, 200 * step, rng.uniform(-0.05, 0.05)))
        else:
            sequence.append(remaining.pop())
    return sequence


def run_engine(engine_class, sequence, species):
    """Return what the engine confirmed at any visit, and whether it ever flagged a conflict."""
    service = DossierService(store=MemoryStore())
    engine = engine_class(service=service)
    service.register_plant("P", "bed", species=species)
    confirmed, flagged = set(), False
    for record in sequence:
        observation = service.submit_observation("P", detections=record["detections"])
        result = engine.evaluate("P", observation.observation_id)
        flagged |= result.plant_status == "uncertain"
        for diagnosis in result.diagnoses:
            if diagnosis.status == "confirmed":
                confirmed.add(diagnosis.possible_condition.removeprefix(f"{species} "))
    return confirmed, flagged


def compare(diseased, healthy, visits, plants, rng, repeat=0.0, mode="exact"):
    names = {"old": LegacyEngine, "new": DiagnosticEngine}
    counts = {n: dict(correct=0, wrong=0, false_alarm=0, flagged=0) for n in names}
    healthy_keys, disease_keys = list(healthy), list(diseased)

    for _ in range(plants):
        species = rng.choice(healthy_keys)
        sequence = visits_for(healthy[species], visits, rng, repeat, mode)
        for name, engine in names.items():
            confirmed, _ = run_engine(engine, sequence, species)
            counts[name]["false_alarm"] += bool(confirmed)

        species, condition = rng.choice(disease_keys)
        sequence = visits_for(diseased[(species, condition)], visits, rng, repeat, mode)
        for name, engine in names.items():
            confirmed, flagged = run_engine(engine, sequence, species)
            counts[name]["correct"] += condition in confirmed
            counts[name]["wrong"] += bool(confirmed - {condition})
            counts[name]["flagged"] += flagged

    return {n: {k: v / plants for k, v in c.items()} for n, c in counts.items()}


def bootstrap(records, visits):
    """Resample the test images; copies of an image count as separate views."""
    rng = random.Random(4100 + visits)
    rows = []
    for b in range(BOOTSTRAPS):
        sample = []
        seen = {}
        for record in (rng.choice(records) for _ in records):
            seen[record["image"]] = seen.get(record["image"], 0) + 1
            sample.append(moved(record, 500 * seen[record["image"]]))
        diseased, healthy = image_pools(sample)
        rows.append(compare(diseased, healthy, visits, PLANTS, rng))
        if b % 50 == 0:
            print("bootstrap", visits, b, flush=True)

    def interval(values):
        values = sorted(values)
        return {
            "mean": sum(values) / len(values),
            "ci95": [values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1]],
        }

    out = {}
    for metric in ("correct", "wrong", "false_alarm", "flagged"):
        out[metric] = {
            "old": interval([r["old"][metric] for r in rows]),
            "new": interval([r["new"][metric] for r in rows]),
            "change": interval([r["new"][metric] - r["old"][metric] for r in rows]),
            "share_below_zero": sum(r["new"][metric] < r["old"][metric] for r in rows) / len(rows),
        }
    return out


def main():
    records = json.loads((RESULTS / "detections_640.json").read_text())
    diseased, healthy = image_pools(records)
    result = {"settings": {"bootstraps": BOOTSTRAPS, "plants": PLANTS, "trials": TRIALS, "threshold": 0.60}}

    result["by_visits"] = {}
    for visits in (2, 3, 4, 5, 6):
        rng = random.Random(100 + visits)
        result["by_visits"][visits] = compare(diseased, healthy, visits, TRIALS, rng)
        print("visits", visits, result["by_visits"][visits], flush=True)

    result["same_view"] = {}
    result["same_mistake_new_angle"] = {}
    for repeat in (0.0, 0.5, 1.0):
        rng = random.Random(int(300 + repeat * 10))
        result["same_view"][repeat] = compare(diseased, healthy, 4, TRIALS, rng, repeat, "exact")
        result["same_mistake_new_angle"][repeat] = compare(diseased, healthy, 4, TRIALS, rng, repeat, "moved")
        print("repeat", repeat, result["same_view"][repeat], result["same_mistake_new_angle"][repeat], flush=True)

    result["bootstrap"] = {visits: bootstrap(records, visits) for visits in (3, 5)}
    (RESULTS / "e6_decision_engine.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result["bootstrap"], indent=1))


if __name__ == "__main__":
    main()
