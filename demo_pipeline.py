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
from dossier import DossierService


def main():
    print("=" * 65)
    print("🌿 C.R.A.P Robotic Perception & Dossier Demonstration")
    print("=" * 65)

    sample_img = Path("vision/sample_images/tomato_leaf.png")
    if not sample_img.exists():
        print(f"Error: Sample image not found at {sample_img}")
        sys.exit(1)

    # 1. Initialize vision detector and bridge
    print("[1/3] Loading YOLOv11s PlantDoc disease model...")
    detector = PlantDocDetector()
    bridge = DossierPerceptionBridge(detector=detector)

    # 2. Run perception & log to Dossier
    plant_id = "PLANT_DEMO_01"
    print(f"[2/3] Analyzing leaf sample ({sample_img}) for plant '{plant_id}'...")
    result = bridge.process_image(
        plant_id=plant_id,
        image_source=sample_img,
        location="Greenhouse_Sector_4",
        conf_threshold=0.30,
    )

    # 3. Annotate and save visual result
    annotated_path = Path("demo_output_annotated.jpg")
    detector.annotate(sample_img, output_path=annotated_path, conf=0.30)
    print(f"[3/3] Annotated bounding box visual saved to: {annotated_path}")

    # Display Dossier results
    plant = result["plant"]
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
    print(f"  - ID      : {obs.observation_id}")
    print(f"  - Symptoms: {obs.visual_symptoms}")
    print(f"  - Source  : {obs.source}")

    print("\nRecorded Diagnoses:")
    for diag in plant.diagnoses:
        print(f"  - Condition : {diag.possible_condition} (Confidence: {diag.confidence*100:.1f}%) [{diag.status.upper()}]")
        for ev in diag.supporting_evidence:
            print(f"    Evidence : {ev}")

    print("=" * 65)
    print("✅ Successfully demonstrated automated vision-to-dossier workflow!\n")


if __name__ == "__main__":
    main()
