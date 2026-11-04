
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Observation:
    observation_id: str
    timestamp: datetime
    visual_symptoms: list[str] = field(default_factory=list)
    image_reference: Optional[str] = None
    sensor_readings: dict[str, Optional[float]] = field(default_factory=dict)
    source: str = "unknown"
    quality: Optional[str] = None
    # Raw model detections (class, species, condition, confidence, bbox),
    # kept so diagnoses can be re-evaluated from the original evidence.
    detections: list[dict] = field(default_factory=list)


@dataclass
class Diagnosis:
    diagnosis_id: str
    timestamp: datetime
    possible_condition: str
    supporting_evidence: list[str] = field(default_factory=list)
    contradicting_evidence: list[str] = field(default_factory=list)
    confidence: Optional[float] = None
    status: str = "suspected"
    observation_ids: list[str] = field(default_factory=list)


@dataclass
class Action:
    action_id: str
    timestamp: datetime
    action_type: str
    reason: str
    status: str = "proposed"
    result: Optional[str] = None
    verification_observation_id: Optional[str] = None
    completed_at: Optional[datetime] = None


@dataclass
class Plant:
    plant_id: str
    location: str
    created_at: datetime = field(default_factory=datetime.now)
    species: Optional[str] = None
    current_status: str = "unassessed"
    observations: list[Observation] = field(default_factory=list)
    diagnoses: list[Diagnosis] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
