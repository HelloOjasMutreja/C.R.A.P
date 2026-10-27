from pathlib import Path
from typing import Optional, Union
import numpy as np

from dossier import DossierService
from .detector import PlantDocDetector, DetectionResult


class DossierPerceptionBridge:
    """Connects YOLO computer vision detections directly to the Dossier plant health log."""

    def __init__(
        self,
        service: Optional[DossierService] = None,
        detector: Optional[PlantDocDetector] = None,
    ):
        self.service = service if service is not None else DossierService()
        self.detector = detector if detector is not None else PlantDocDetector()

    def process_image(
        self,
        plant_id: str,
        image_source: Union[str, Path, np.ndarray],
        location: str = "field_section_A",
        species: Optional[str] = None,
        sensor_readings: Optional[dict] = None,
        conf_threshold: float = 0.35,
        iou_threshold: float = 0.45,
        auto_register: bool = True,
    ) -> dict:
        """
        Runs vision detection on an image and logs structured observations and diagnoses into Dossier.
        """
        image_ref = str(image_source) if isinstance(image_source, (str, Path)) else "in_memory_image"

        # Check or register plant
        try:
            self.service.get_plant(plant_id)
        except ValueError:
            if auto_register:
                self.service.register_plant(
                    plant_id=plant_id,
                    location=location,
                    species=species,
                )
            else:
                raise

        # 1. Run YOLO vision detector
        detections = self.detector.predict(
            source=image_source,
            conf=conf_threshold,
            iou=iou_threshold,
        )

        summary = self.detector.summarize(detections)

        # 2. Extract symptoms & submit Observation
        visual_symptoms = []
        if summary["diseases_found"]:
            for d in summary["diseases_found"]:
                visual_symptoms.append(f"{summary['species']}: {d}")
        elif summary["healthy_count"] > 0:
            visual_symptoms.append("healthy foliage without visible lesions")
        else:
            visual_symptoms.append("no plant leaves detected")

        observation = self.service.submit_observation(
            plant_id=plant_id,
            visual_symptoms=visual_symptoms,
            image_reference=image_ref,
            sensor_readings=sensor_readings or {},
            source="yolo_plantdoc_pipeline",
            quality="high" if detections else "low",
        )

        # 3. Record Diagnoses for detected diseases
        recorded_diagnoses = []
        diseased_detections = [d for d in detections if not d.is_healthy]

        if diseased_detections:
            condition_map: dict[str, list[DetectionResult]] = {}
            for d in diseased_detections:
                condition_map.setdefault(d.condition, []).append(d)

            for condition, group in condition_map.items():
                top_det = max(group, key=lambda x: x.confidence)
                supporting = [
                    f"Detected in bbox {d.bbox} (conf: {d.confidence*100:.1f}%)"
                    for d in group
                ]

                diagnosis = self.service.record_diagnosis(
                    plant_id=plant_id,
                    possible_condition=f"{top_det.species} {condition}",
                    supporting_evidence=supporting,
                    contradicting_evidence=[],
                    confidence=round(top_det.confidence, 4),
                    status="confirmed" if top_det.confidence >= 0.70 else "suspected",
                )
                recorded_diagnoses.append(diagnosis)
        elif summary["healthy_count"] > 0:
            max_healthy_conf = max(d.confidence for d in detections)
            diagnosis = self.service.record_diagnosis(
                plant_id=plant_id,
                possible_condition="Healthy Foliage",
                supporting_evidence=[f"Verified healthy leaf with {max_healthy_conf*100:.1f}% confidence"],
                confidence=round(max_healthy_conf, 4),
                status="healthy",
            )
            recorded_diagnoses.append(diagnosis)

        # Reload updated plant to sync observations and diagnoses
        plant = self.service.get_plant(plant_id)
        if not plant.species and summary["species"]:
            plant.species = summary["species"]

        if diseased_detections:
            plant.current_status = "diseased"
        elif summary["healthy_count"] > 0:
            plant.current_status = "healthy"

        self.service.store.save_plants(
            self.service.store.load_plants() | {plant.plant_id: plant}
        )

        return {
            "plant": plant,
            "observation": observation,
            "diagnoses": recorded_diagnoses,
            "detections": detections,
            "summary": summary,
        }
