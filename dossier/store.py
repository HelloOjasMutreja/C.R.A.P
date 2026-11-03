
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .models import Plant, Observation, Diagnosis, Action

# Anchor the default file to the package, not the current working directory.
DEFAULT_FILE_PATH = Path(__file__).parent / "data" / "plants.json"


class PlantStore:
    def __init__(self, file_path=DEFAULT_FILE_PATH):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def load_plants(self):
        if not self.file_path.exists():
            return {}

        with self.file_path.open("r", encoding="utf-8") as file:
            content = file.read()

        # An empty file means no plants have been saved yet.
        if not content.strip():
            return {}

        data = json.loads(content)

        plants = {}

        for plant_data in data:
            plant = self._plant_from_dict(plant_data)
            plants[plant.plant_id] = plant

        return plants

    def save_plants(self, plants):
        data = [asdict(plant) for plant in plants.values()]

        with self.file_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=4, default=self._json_serializer)

    def get_plant(self, plant_id):
        plants = self.load_plants()
        return plants.get(plant_id)

    def add_plant(self, plant):
        plants = self.load_plants()

        if plant.plant_id in plants:
            raise ValueError(f"Plant ID already exists: {plant.plant_id}")

        plants[plant.plant_id] = plant
        self.save_plants(plants)

    @staticmethod
    def _json_serializer(value):
        if isinstance(value, datetime):
            return value.isoformat()

        raise TypeError(f"Cannot serialize type: {type(value).__name__}")

    @staticmethod
    def _parse_datetime(value):
        return datetime.fromisoformat(value)

    @classmethod
    def _plant_from_dict(cls, data):
        observations = [
            Observation(
                observation_id=item["observation_id"],
                timestamp=cls._parse_datetime(item["timestamp"]),
                visual_symptoms=item.get("visual_symptoms", []),
                image_reference=item.get("image_reference"),
                sensor_readings=item.get("sensor_readings", {}),
                source=item.get("source", "unknown"),
                quality=item.get("quality"),
                detections=item.get("detections", []),
            )
            for item in data.get("observations", [])
        ]

        diagnoses = [
            Diagnosis(
                diagnosis_id=item["diagnosis_id"],
                timestamp=cls._parse_datetime(item["timestamp"]),
                possible_condition=item["possible_condition"],
                supporting_evidence=item.get("supporting_evidence", []),
                contradicting_evidence=item.get("contradicting_evidence", []),
                confidence=item.get("confidence"),
                status=item.get("status", "suspected"),
                observation_ids=item.get("observation_ids", []),
            )
            for item in data.get("diagnoses", [])
        ]

        actions = [
            Action(
                action_id=item["action_id"],
                timestamp=cls._parse_datetime(item["timestamp"]),
                action_type=item["action_type"],
                reason=item["reason"],
                status=item.get("status", "proposed"),
                result=item.get("result"),
                verification_observation_id=item.get(
                    "verification_observation_id"
                ),
            )
            for item in data.get("actions", [])
        ]

        return Plant(
            plant_id=data["plant_id"],
            location=data["location"],
            created_at=cls._parse_datetime(data["created_at"]),
            species=data.get("species"),
            current_status=data.get("current_status", "unassessed"),
            observations=observations,
            diagnoses=diagnoses,
            actions=actions,
        )
