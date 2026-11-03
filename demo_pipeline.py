#!/usr/bin/env python3
"""
demo_pipeline.py
================
Demonstration script connecting YOLO plant disease detection directly
to the C.R.A.P Dossier health log.
"""

import sys
from pathlib import Path
from vision import PlantDocDetector, DossierPerceptionBridge
from diagnostics import DiagnosticEngine
from dossier import DossierService


def main():
    print("=" * 65)
    print("🌿 C.R.A.P Robotic Perception & Dossier Demonstration")
    print("=" * 65)

    sample_img = Path(__file__).parent / "vision" / "sample_images" / "tomato_leaf.png"
    if not sample_img.exists():
        print(f"Error: Sample image not found at {sample_img}")
        sys.exit(1)

    # 1. Initialize vision detector, bridge and diagnostic engine
    print("[1/4] Loading YOLOv11s PlantDoc disease model...")
    detector = PlantDocDetector()
    service = DossierService()
    bridge = DossierPerceptionBridge(service=service, detector=detector)
    engine = DiagnosticEngine(service=service)

    # 2. Run perception & log the observation to Dossier
    plant_id = "PLANT_DEMO_01"
    print(f"[2/4] Analyzing leaf sample ({sample_img}) for plant '{plant_id}'...")
    result = bridge.process_image(
        plant_id=plant_id,
        image_source=sample_img,
        location="Greenhouse_Sector_4",
        conf_threshold=0.30,
    )

    # 3. Evaluate the observation against the plant's history
    print("[3/4] Evaluating evidence with the diagnostic engine...")
    evaluation = engine.evaluate(plant_id, result["observation"].observation_id)

    # 4. Annotate and save visual result
    annotated_path = Path("demo_output_annotated.jpg")
    detector.annotate(sample_img, output_path=annotated_path, conf=0.30)
    print(f"[4/4] Annotated bounding box visual saved to: {annotated_path}")

    # Display Dossier results
    plant = service.get_plant(plant_id)
    summary = result["summary"]
    print("\n" + "=" * 65)
    print("📋 DOSSIER SUMMARY REPORT")
    print("=" * 65)
    print(f"Plant ID         : {plant.plant_id}")
    print(f"Species          : {plant.species}")
    print(f"Location         : {plant.location}")
    print(f"Current Status   : {plant.current_status.upper()}")
    print(f"Total Detections : {summary['total_detections']}")
    print(f"Diseases Found   : {', '.join(summary['diseases_found']) if summary['diseases_found'] else 'None (Healthy)'}")

    print("\nRecent Observation:")
    obs = plant.observations[-1]
    print(f"  - ID        : {obs.observation_id}")
    print(f"  - Detections: {len(obs.detections)}")
    print(f"  - Source    : {obs.source}")

    print("\nDiagnoses From This Observation:")
    if not evaluation.diagnoses:
        print("  - None")
    for diag in evaluation.diagnoses:
        print(f"  - Condition : {diag.possible_condition} (Confidence: {diag.confidence*100:.1f}%) [{diag.status.upper()}]")
        for ev in diag.supporting_evidence:
            print(f"    Evidence : {ev}")
        for ev in diag.contradicting_evidence:
            print(f"    Against  : {ev}")
    for note in evaluation.notes:
        print(f"  - Note      : {note}")

    print("=" * 65)
    print("✅ Successfully demonstrated automated vision-to-dossier workflow!\n")


if __name__ == "__main__":
    main()
