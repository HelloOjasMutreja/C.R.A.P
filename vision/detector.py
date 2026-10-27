from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union
import cv2
import numpy as np

# Anchor default weights path relative to the package directory
DEFAULT_WEIGHTS_PATH = Path(__file__).parent / "weights" / "best.pt"

# Mapping of PlantDoc classes to normalized species and disease conditions
CLASS_METADATA = {
    0: {"name": "Apple Scab Leaf", "species": "Apple", "condition": "Apple Scab", "is_healthy": False},
    1: {"name": "Apple leaf", "species": "Apple", "condition": "Healthy", "is_healthy": True},
    2: {"name": "Apple rust leaf", "species": "Apple", "condition": "Apple Rust", "is_healthy": False},
    3: {"name": "Bell_pepper leaf", "species": "Bell Pepper", "condition": "Healthy", "is_healthy": True},
    4: {"name": "Bell_pepper leaf spot", "species": "Bell Pepper", "condition": "Bacterial Spot", "is_healthy": False},
    5: {"name": "Blueberry leaf", "species": "Blueberry", "condition": "Healthy", "is_healthy": True},
    6: {"name": "Cherry leaf", "species": "Cherry", "condition": "Healthy", "is_healthy": True},
    7: {"name": "Corn Gray leaf spot", "species": "Corn", "condition": "Gray Leaf Spot", "is_healthy": False},
    8: {"name": "Corn leaf blight", "species": "Corn", "condition": "Leaf Blight", "is_healthy": False},
    9: {"name": "Corn rust leaf", "species": "Corn", "condition": "Common Rust", "is_healthy": False},
    10: {"name": "Peach leaf", "species": "Peach", "condition": "Healthy", "is_healthy": True},
    11: {"name": "Potato leaf", "species": "Potato", "condition": "Healthy", "is_healthy": True},
    12: {"name": "Potato leaf early blight", "species": "Potato", "condition": "Early Blight", "is_healthy": False},
    13: {"name": "Potato leaf late blight", "species": "Potato", "condition": "Late Blight", "is_healthy": False},
    14: {"name": "Raspberry leaf", "species": "Raspberry", "condition": "Healthy", "is_healthy": True},
    15: {"name": "Soyabean leaf", "species": "Soybean", "condition": "Healthy", "is_healthy": True},
    16: {"name": "Squash Powdery mildew leaf", "species": "Squash", "condition": "Powdery Mildew", "is_healthy": False},
    17: {"name": "Strawberry leaf", "species": "Strawberry", "condition": "Healthy", "is_healthy": True},
    18: {"name": "Tomato Early blight leaf", "species": "Tomato", "condition": "Early Blight", "is_healthy": False},
    19: {"name": "Tomato Septoria leaf spot", "species": "Tomato", "condition": "Septoria Leaf Spot", "is_healthy": False},
    20: {"name": "Tomato leaf", "species": "Tomato", "condition": "Healthy", "is_healthy": True},
    21: {"name": "Tomato leaf bacterial spot", "species": "Tomato", "condition": "Bacterial Spot", "is_healthy": False},
    22: {"name": "Tomato leaf late blight", "species": "Tomato", "condition": "Late Blight", "is_healthy": False},
    23: {"name": "Tomato leaf mosaic virus", "species": "Tomato", "condition": "Mosaic Virus", "is_healthy": False},
    24: {"name": "Tomato leaf yellow virus", "species": "Tomato", "condition": "Yellow Leaf Curl Virus", "is_healthy": False},
    25: {"name": "Tomato mold leaf", "species": "Tomato", "condition": "Leaf Mold", "is_healthy": False},
    26: {"name": "Tomato two spotted spider mites leaf", "species": "Tomato", "condition": "Two-spotted Spider Mite", "is_healthy": False},
    27: {"name": "grape leaf", "species": "Grape", "condition": "Healthy", "is_healthy": True},
    28: {"name": "grape leaf black rot", "species": "Grape", "condition": "Black Rot", "is_healthy": False},
}


@dataclass
class DetectionResult:
    class_id: int
    raw_class_name: str
    species: str
    condition: str
    is_healthy: bool
    confidence: float
    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2)


class PlantDocDetector:
    """Production YOLO perception module for PlantDoc disease and species detection."""

    def __init__(self, weights_path: Optional[Union[str, Path]] = None):
        self.weights_path = Path(weights_path) if weights_path else DEFAULT_WEIGHTS_PATH
        if not self.weights_path.exists():
            raise FileNotFoundError(f"Model weights not found at: {self.weights_path}")

        from ultralytics import YOLO
        self.model = YOLO(str(self.weights_path))

    def predict(
        self,
        source: Union[str, Path, np.ndarray],
        conf: float = 0.25,
        iou: float = 0.45,
    ) -> list[DetectionResult]:
        """Run object detection on an image path or numpy BGR image array."""
        results = self.model.predict(
            source=source if isinstance(source, np.ndarray) else str(source),
            conf=conf,
            iou=iou,
            verbose=False,
        )

        detections: list[DetectionResult] = []
        for r in results:
            for box in r.boxes:
                cls_id = int(box.cls[0].item())
                confidence = float(box.conf[0].item())
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())

                metadata = CLASS_METADATA.get(
                    cls_id,
                    {
                        "name": self.model.names.get(cls_id, f"Class_{cls_id}"),
                        "species": "Unknown",
                        "condition": "Unknown",
                        "is_healthy": False,
                    },
                )

                detections.append(
                    DetectionResult(
                        class_id=cls_id,
                        raw_class_name=metadata["name"],
                        species=metadata["species"],
                        condition=metadata["condition"],
                        is_healthy=metadata["is_healthy"],
                        confidence=confidence,
                        bbox=(x1, y1, x2, y2),
                    )
                )

        return detections

    def annotate(
        self,
        source: Union[str, Path, np.ndarray],
        output_path: Optional[Union[str, Path]] = None,
        conf: float = 0.25,
        iou: float = 0.45,
    ) -> np.ndarray:
        """Run detection and render labeled bounding boxes onto the image."""
        if isinstance(source, (str, Path)):
            img = cv2.imread(str(source))
            if img is None:
                raise FileNotFoundError(f"Could not read image from {source}")
        else:
            img = source.copy()

        detections = self.predict(img, conf=conf, iou=iou)
        h, w = img.shape[:2]

        for d in detections:
            x1, y1, x2, y2 = d.bbox
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)

            color = (60, 180, 75) if d.is_healthy else (30, 70, 230)

            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)

            label = f"{d.species}: {d.condition} ({d.confidence*100:.0f}%)"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(
                img,
                (x1, max(0, y1 - th - 6)),
                (x1 + tw + 6, max(y1, th + 6)),
                color,
                -1,
            )
            cv2.putText(
                img,
                label,
                (x1 + 3, max(y1 - 3, th + 3)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

        if output_path:
            out_p = Path(output_path)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out_p), img)

        return img

    @staticmethod
    def summarize(detections: list[DetectionResult]) -> dict:
        """Summarize detection results for high-level plant health assessment."""
        if not detections:
            return {
                "total_detections": 0,
                "overall_status": "unassessed",
                "species": None,
                "diseases_found": [],
                "healthy_count": 0,
                "diseased_count": 0,
            }

        species_counts: dict[str, int] = {}
        for d in detections:
            species_counts[d.species] = species_counts.get(d.species, 0) + 1
        dominant_species = max(species_counts.items(), key=lambda x: x[1])[0]

        diseased = [d for d in detections if not d.is_healthy]
        healthy = [d for d in detections if d.is_healthy]

        unique_diseases = list(dict.fromkeys(d.condition for d in diseased))
        overall_status = "diseased" if diseased else "healthy"

        return {
            "total_detections": len(detections),
            "overall_status": overall_status,
            "species": dominant_species,
            "diseases_found": unique_diseases,
            "healthy_count": len(healthy),
            "diseased_count": len(diseased),
        }
