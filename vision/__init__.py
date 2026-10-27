from .detector import (
    PlantDocDetector,
    DetectionResult,
    CLASS_METADATA,
    DEFAULT_WEIGHTS_PATH,
)
from .bridge import DossierPerceptionBridge

__all__ = [
    "PlantDocDetector",
    "DetectionResult",
    "CLASS_METADATA",
    "DEFAULT_WEIGHTS_PATH",
    "DossierPerceptionBridge",
]
