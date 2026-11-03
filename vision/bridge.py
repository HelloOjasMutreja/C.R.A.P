from dataclasses import asdict
from pathlib import Path
from typing import Optional, Union
import numpy as np

from dossier import DossierService
from .detector import PlantDocDetector


class DossierPerceptionBridge:
    """Records YOLO detections as observations in the Dossier plant health log.

    The bridge only records what the camera saw. Deciding what the detections
    mean (suspected or confirmed conditions, plant status) is left to the
    diagnostic engine, which can weigh them against the plant's history.
    """

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
        Runs vision detection on an image and logs the raw detections as an Observation.
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

        # 2. Submit Observation with the raw detections as evidence
        detection_records = [
            {**asdict(d), "bbox": list(d.bbox), "confidence": round(d.confidence, 4)}
            for d in detections
        ]

        observation = self.service.submit_observation(
            plant_id=plant_id,
            image_reference=image_ref,
            sensor_readings=sensor_readings or {},
            source="yolo_plantdoc_pipeline",
            quality="high" if detections else "low",
            detections=detection_records,
        )

        # 3. Fill in species from the image only if it was never set
        plant = self.service.get_plant(plant_id)
        if not plant.species and summary["species"]:
            plant = self.service.update_plant(plant_id, species=summary["species"])

        return {
            "plant": plant,
            "observation": observation,
            "detections": detections,
            "summary": summary,
        }
