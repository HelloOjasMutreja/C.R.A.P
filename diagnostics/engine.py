from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from dossier import DossierService


# Detections this similar come from effectively the same frame.
SAME_VIEW_OVERLAP = 0.9
SAME_VIEW_CONFIDENCE = 0.03

# A plant in one of these states keeps it when a frame shows no usable leaves.
AT_RISK = ("diseased", "suspected_disease", "uncertain")

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


def box_overlap(a, b):
    """Intersection over union of two (x1, y1, x2, y2) boxes."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    overlap = width * height
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return overlap / (area_a + area_b - overlap)


def same_view(first, second):
    """True when two observations are effectively the same frame.

    A second look only adds evidence if it could have turned out differently, so
    matching detections in matching places do not count as a new sighting.
    """
    if first.image_reference and first.image_reference == second.image_reference:
        return True
    if not first.detections or len(first.detections) != len(second.detections):
        return False

    unmatched = list(second.detections)
    for a in first.detections:
        match = next(
            (
                b for b in unmatched
                if a["condition"] == b["condition"]
                and a["species"] == b["species"]
                and abs(a["confidence"] - b["confidence"]) <= SAME_VIEW_CONFIDENCE
                and box_overlap(a["bbox"], b["bbox"]) >= SAME_VIEW_OVERLAP
            ),
            None,
        )
        if match is None:
            return False
        unmatched.remove(match)
    return True


class DiagnosticEngine:
    """Turns recorded observations into suspected or confirmed plant conditions.

    Measured on real detections, the detector's confidence says little about
    whether it is right, so the engine relies on agreement between different
    views instead. The rules stay simple enough to explain:

    1. Only detections of the plant's own species at or above ``min_confidence``
       count as evidence. Other species are ignored and noted.
    2. The evidence is the last ``lookback`` + 1 distinct views since the plant
       was last sprayed. Repeats of a view and frames without leaves do not count.
    3. A view votes for a condition seen at ``confirm_confidence`` or higher.
    4. A condition is ``confirmed`` when it has at least two votes, a strict
       majority of the views, and more votes than any rival. One image is never
       enough to confirm a disease.
    5. Rival conditions tied at two or more votes make the plant ``uncertain``,
       which goes to a person: treating the wrong disease is the costly mistake.
    6. Status comes from the whole window, so one healthy or blurry view does not
       undo a diagnosis, and a disease fades as healthy views outvote it.
    7. High humidity is noted as context for humidity-favoured conditions. It
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
        is_latest = index == len(plant.observations) - 1

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
            # A bad frame says nothing about a plant already under suspicion.
            status = plant.current_status if plant.current_status in AT_RISK else "needs_reinspection"
            return self._finish(plant_id, target, status, [], notes, is_latest)

        views, repeated = self._distinct_views(plant, index, species)
        if repeated:
            notes.append(
                "This looks like the same view as an earlier visit, so it is not a new "
                "sighting. Move or zoom in for a second opinion."
            )

        votes = Counter()
        for view in views:
            votes.update(self._conditions(view, species, self.confirm_confidence).keys())

        most = max(votes.values(), default=0)
        leaders = sorted(c for c, count in votes.items() if count == most)
        conflict = most >= 2 and len(leaders) > 1
        confirmed = leaders[0] if most >= 2 and len(leaders) == 1 and most * 2 > len(views) else None

        seen_now = self._conditions(target, species, self.min_confidence)
        active = set(seen_now) | {c for c, count in votes.items() if count * 2 >= len(views)}
        if confirmed or conflict:
            active |= set(votes)

        if conflict:
            names = " and ".join(leaders)
            notes.append(f"{names} are tied at {most} views each, so a person should decide.")

        diagnoses = [
            self._diagnose(
                plant_id, species, condition, relevant, target, views, votes[condition],
                "confirmed" if condition == confirmed else "suspected",
            )
            for condition in sorted(active, key=lambda c: (-votes[c], c))
        ]

        if confirmed:
            status = "diseased"
        elif conflict:
            status = "uncertain"
        elif active:
            status = "suspected_disease"
        else:
            status = "healthy"

        return self._finish(plant_id, target, status, diagnoses, notes, is_latest)

    def _diagnose(self, plant_id, species, condition, relevant, target, views, vote_count, status):
        group = [d for d in relevant if not d["is_healthy"] and d["condition"] == condition]
        healthy = [d for d in relevant if d["is_healthy"]]
        earlier = [view for view in reversed(views) if view is not target]

        supporting = []
        contradicting = []
        observation_ids = [target.observation_id]
        confidences = [d["confidence"] for d in group]

        if group:
            supporting.append(
                f"{len(group)} {species} leaf detection(s) show {condition} in "
                f"{target.observation_id} (highest confidence {max(confidences):.0%})."
            )
        else:
            contradicting.append(f"Not detected in the latest observation {target.observation_id}.")

        if healthy:
            contradicting.append(
                f"{len(healthy)} healthy {species} leaf detection(s) in the same image."
            )

        humidity = target.sensor_readings.get("humidity_rh")
        if humidity is not None and humidity >= self.high_humidity and condition in HUMIDITY_FAVOURED:
            supporting.append(
                f"Air humidity was {humidity:.0f}%, which favours {condition}; context only."
            )

        for view in earlier:
            matches = self._conditions(view, species, self.min_confidence)
            if condition in matches:
                supporting.append(
                    f"Also detected in earlier observation {view.observation_id} "
                    f"(highest confidence {matches[condition]:.0%})."
                )
                observation_ids.append(view.observation_id)
                confidences.append(matches[condition])
            else:
                contradicting.append(f"Not detected in earlier observation {view.observation_id}.")

        if len(views) > 1:
            supporting.append(f"Seen clearly in {vote_count} of {len(views)} distinct views.")
        elif status != "confirmed":
            supporting.append(
                "First observation of this plant; a repeat observation is needed to confirm."
            )

        return self.service.record_diagnosis(
            plant_id=plant_id,
            possible_condition=f"{species} {condition}",
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            confidence=round(max(confidences), 4),
            status=status,
            observation_ids=observation_ids,
        )

    def _finish(self, plant_id, target, status, diagnoses, notes, is_latest=True):
        # Looking back at an old visit must not overwrite what is true today.
        if is_latest:
            self.service.update_plant(plant_id, current_status=status)
        else:
            status = self.service.get_plant(plant_id).current_status
        return EngineResult(
            plant_id=plant_id,
            observation_id=target.observation_id,
            plant_status=status,
            diagnoses=diagnoses,
            notes=notes,
        )

    def _distinct_views(self, plant, index, species):
        """The usable, distinct observations in the evidence window, oldest first."""
        sprayed = [
            a.completed_at for a in plant.actions
            if a.action_type == "spray_plant" and a.status == "completed" and a.completed_at
        ]
        since = max(sprayed, default=None)

        views = []
        repeated = False
        for observation in plant.observations[: index + 1]:
            if since is not None and observation.timestamp <= since:
                continue
            if not self._relevant(observation, species):
                continue
            if any(same_view(view, observation) for view in views):
                repeated = observation is plant.observations[index]
                continue
            views.append(observation)

        return views[-(self.lookback + 1):], repeated

    def _conditions(self, observation, species, threshold):
        """Highest confidence of each disease on this plant at or above threshold."""
        found = {}
        for d in self._relevant(observation, species):
            if not d["is_healthy"] and d["confidence"] >= threshold:
                found[d["condition"]] = max(found.get(d["condition"], 0), d["confidence"])
        return found

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
