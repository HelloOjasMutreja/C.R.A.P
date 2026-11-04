from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from dossier import DossierService


# Conditions that high air humidity is commonly associated with. Humidity only ever
# adds context to a condition the camera already saw; it never creates or confirms one.
HUMIDITY_FAVOURED = {
    "Apple Scab",
    "Apple Rust",
    "Black Rot",
    "Common Rust",
    "Early Blight",
    "Gray Leaf Spot",
    "Late Blight",
    "Leaf Blight",
    "Leaf Mold",
    "Septoria Leaf Spot",
}


@dataclass
class EngineResult:
    plant_id: str
    observation_id: Optional[str]
    plant_status: str
    diagnoses: list = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class DiagnosticEngine:
    """Turns recorded observations into suspected or confirmed plant conditions.

    The rules are deliberately simple so every decision can be explained:

    1. Only detections of the plant's own species at or above
       ``min_confidence`` count as evidence. Other species are ignored and
       noted, since they are usually misclassifications or a neighbouring plant.
    2. A condition seen in a single observation is only ``suspected``.
    3. It becomes ``confirmed`` when it is seen at ``confirm_confidence`` or
       higher both now and in at least one of the last ``lookback`` earlier
       observations. One image is never enough to confirm a disease.
    4. Plant status follows the strongest result: ``diseased`` (any confirmed),
       ``suspected_disease`` (any suspected), ``healthy`` (only healthy leaves),
       or ``needs_reinspection`` (no usable leaves in the image).
    5. High humidity is noted as context for humidity-favoured conditions. It
       never changes a diagnosis's status.

    The engine reads observations and writes diagnoses and plant status; it
    never runs the camera model itself.
    """

    def __init__(
        self,
        service: Optional[DossierService] = None,
        min_confidence: float = 0.35,
        confirm_confidence: float = 0.60,
        lookback: int = 3,
        high_humidity: float = 70.0,
    ):
        self.service = service if service is not None else DossierService()
        self.min_confidence = min_confidence
        self.confirm_confidence = confirm_confidence
        self.lookback = lookback
        self.high_humidity = high_humidity

    def evaluate(self, plant_id: str, observation_id: Optional[str] = None) -> EngineResult:
        """Evaluate one observation (the latest by default) and record the outcome."""
        plant = self.service.get_plant(plant_id)

        if not plant.observations:
            return EngineResult(
                plant_id=plant_id,
                observation_id=None,
                plant_status=plant.current_status,
                notes=["No observations recorded yet."],
            )

        index = self._observation_index(plant, observation_id)
        target = plant.observations[index]

        # Evaluating the same observation twice should not duplicate diagnoses.
        existing = [
            d for d in plant.diagnoses
            if d.observation_ids and d.observation_ids[0] == target.observation_id
        ]
        if existing:
            return EngineResult(
                plant_id=plant_id,
                observation_id=target.observation_id,
                plant_status=plant.current_status,
                diagnoses=existing,
                notes=[f"{target.observation_id} was already evaluated."],
            )

        notes = []
        species = plant.species or self._dominant_species(target)
        relevant = self._relevant(target, species)

        off_species = [
            d for d in target.detections
            if d["species"] != species and d["confidence"] >= self.min_confidence
        ]
        if off_species:
            names = ", ".join(sorted({d["raw_class_name"] for d in off_species}))
            notes.append(
                f"Ignored {len(off_species)} detection(s) of other species "
                f"({names}); the plant is recorded as {species}."
            )

        if not relevant:
            notes.append(
                f"No {species or 'plant'} leaves detected at "
                f"{self.min_confidence:.0%} confidence or higher in {target.observation_id}."
            )
            return self._finish(plant_id, target, "needs_reinspection", [], notes)

        # Earlier observations that actually contain usable leaf detections.
        history = [
            obs for obs in reversed(plant.observations[:index])
            if self._relevant(obs, species)
        ][: self.lookback]

        healthy = [d for d in relevant if d["is_healthy"]]
        by_condition: dict[str, list[dict]] = {}
        for d in relevant:
            if not d["is_healthy"]:
                by_condition.setdefault(d["condition"], []).append(d)

        diagnoses = []
        for condition, group in by_condition.items():
            diagnoses.append(
                self._diagnose(plant_id, species, condition, group, healthy, target, history)
            )

        if any(d.status == "confirmed" for d in diagnoses):
            status = "diseased"
        elif diagnoses:
            status = "suspected_disease"
        else:
            status = "healthy"

        return self._finish(plant_id, target, status, diagnoses, notes)

    def _diagnose(self, plant_id, species, condition, group, healthy, target, history):
        top = max(d["confidence"] for d in group)

        supporting = [
            f"{len(group)} {species} leaf detection(s) show {condition} in "
            f"{target.observation_id} (highest confidence {top:.0%})."
        ]
        contradicting = []
        if healthy:
            contradicting.append(
                f"{len(healthy)} healthy {species} leaf detection(s) in the same image."
            )

        humidity = target.sensor_readings.get("humidity_rh")
        if humidity is not None and humidity >= self.high_humidity and condition in HUMIDITY_FAVOURED:
            supporting.append(
                f"Air humidity was {humidity:.0f}%, which favours {condition}; context only."
            )

        observation_ids = [target.observation_id]
        confirmed_before = False

        for obs in history:
            matches = [
                d for d in self._relevant(obs, species)
                if not d["is_healthy"] and d["condition"] == condition
            ]
            if matches:
                earlier_top = max(d["confidence"] for d in matches)
                supporting.append(
                    f"Also detected in earlier observation {obs.observation_id} "
                    f"(highest confidence {earlier_top:.0%})."
                )
                observation_ids.append(obs.observation_id)
                confirmed_before |= earlier_top >= self.confirm_confidence
            else:
                contradicting.append(
                    f"Not detected in earlier observation {obs.observation_id}."
                )

        if top >= self.confirm_confidence and confirmed_before:
            status = "confirmed"
        else:
            status = "suspected"
            if not history:
                supporting.append(
                    "First observation of this plant; a repeat observation is needed to confirm."
                )

        return self.service.record_diagnosis(
            plant_id=plant_id,
            possible_condition=f"{species} {condition}",
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            confidence=round(top, 4),
            status=status,
            observation_ids=observation_ids,
        )

    def _finish(self, plant_id, target, status, diagnoses, notes):
        self.service.update_plant(plant_id, current_status=status)
        return EngineResult(
            plant_id=plant_id,
            observation_id=target.observation_id,
            plant_status=status,
            diagnoses=diagnoses,
            notes=notes,
        )

    def _relevant(self, observation, species):
        return [
            d for d in observation.detections
            if d["species"] == species and d["confidence"] >= self.min_confidence
        ]

    def _dominant_species(self, observation):
        counts = Counter(
            d["species"] for d in observation.detections
            if d["confidence"] >= self.min_confidence
        )
        return counts.most_common(1)[0][0] if counts else None

    @staticmethod
    def _observation_index(plant, observation_id):
        if observation_id is None:
            return len(plant.observations) - 1

        for i, obs in enumerate(plant.observations):
            if obs.observation_id == observation_id:
                return i

        raise ValueError(f"Observation not found: {observation_id}")
