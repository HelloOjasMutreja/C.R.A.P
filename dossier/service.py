
from datetime import datetime

from .models import Plant, Observation, Diagnosis, Action
from .store import PlantStore


class DossierService:
    def __init__(self, store=None):
        self.store = store if store is not None else PlantStore()

    def register_plant(self, plant_id, location, species=None):
        plant = Plant(
            plant_id=plant_id,
            location=location,
            species=species,
        )

        self.store.add_plant(plant)
        return plant

    def get_plant(self, plant_id):
        plant = self.store.get_plant(plant_id)

        if plant is None:
            raise ValueError(f"Plant not found: {plant_id}")

        return plant

    def list_plants(self):
        return list(self.store.load_plants().values())

    def update_plant(self, plant_id, species=None, current_status=None):
        plant = self.get_plant(plant_id)

        if species is not None:
            plant.species = species

        if current_status is not None:
            plant.current_status = current_status

        self.store.save_plants(self.store.load_plants() | {
            plant.plant_id: plant
        })

        return plant

    def submit_observation(
        self,
        plant_id,
        visual_symptoms=None,
        image_reference=None,
        sensor_readings=None,
        source="unknown",
        quality=None,
        detections=None,
    ):
        plant = self.get_plant(plant_id)

        observation = Observation(
            observation_id=self._new_id("OBS"),
            timestamp=datetime.now(),
            visual_symptoms=visual_symptoms or [],
            image_reference=image_reference,
            sensor_readings=sensor_readings or {},
            source=source,
            quality=quality,
            detections=detections or [],
        )

        plant.observations.append(observation)
        self.store.save_plants(self.store.load_plants() | {
            plant.plant_id: plant
        })

        return observation

    def record_diagnosis(
        self,
        plant_id,
        possible_condition,
        supporting_evidence=None,
        contradicting_evidence=None,
        confidence=None,
        status="suspected",
        observation_ids=None,
    ):
        plant = self.get_plant(plant_id)

        diagnosis = Diagnosis(
            diagnosis_id=self._new_id("DIA"),
            timestamp=datetime.now(),
            possible_condition=possible_condition,
            supporting_evidence=supporting_evidence or [],
            contradicting_evidence=contradicting_evidence or [],
            confidence=confidence,
            status=status,
            observation_ids=observation_ids or [],
        )

        plant.diagnoses.append(diagnosis)
        self.store.save_plants(self.store.load_plants() | {
            plant.plant_id: plant
        })

        return diagnosis

    def record_action(
        self,
        plant_id,
        action_type,
        reason,
        status="proposed",
        result=None,
        verification_observation_id=None,
    ):
        plant = self.get_plant(plant_id)

        action = Action(
            action_id=self._new_id("ACT"),
            timestamp=datetime.now(),
            action_type=action_type,
            reason=reason,
            status=status,
            result=result,
            verification_observation_id=verification_observation_id,
        )

        plant.actions.append(action)
        self.store.save_plants(self.store.load_plants() | {
            plant.plant_id: plant
        })

        return action

    @staticmethod
    def _new_id(prefix):
        from uuid import uuid4
        return f"{prefix}_{uuid4().hex[:8]}"
