"""Live phone feed server.

The phone opens the page, streams camera frames over a WebSocket, and gets
YOLO detections back to draw over its own live video. Tapping "record" posts a
full-resolution still, which is saved as a visit in the dossier and evaluated
by the diagnostic engine, and the action manager proposes what the robot
should do next. Actions only run when the phone asks for them.
"""

import asyncio
import threading
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from actions import ActionManager
from diagnostics import DiagnosticEngine
from dossier import DossierService
from hardware import RobotError, SimulatedRobot
from vision import DossierPerceptionBridge
from .markers import PlantTagReader

STATIC_DIR = Path(__file__).parent / "static"


def plant_summary(plant) -> dict:
    """Compact view of a plant record for the phone's dossier panel."""
    last = plant.observations[-1].timestamp.isoformat() if plant.observations else None
    return {
        "plant_id": plant.plant_id,
        "location": plant.location,
        "species": plant.species,
        "status": plant.current_status,
        "visits": len(plant.observations),
        "last_visit": last,
        "diagnoses": [
            {
                "condition": d.possible_condition,
                "status": d.status,
                "confidence": d.confidence,
                "supporting": d.supporting_evidence,
                "contradicting": d.contradicting_evidence,
                "timestamp": d.timestamp.isoformat(),
            }
            for d in reversed(plant.diagnoses[-5:])
        ],
        "actions": [action_summary(a) for a in reversed(plant.actions[-5:])],
    }


def action_summary(action) -> dict:
    return {
        "action_id": action.action_id,
        "type": action.action_type,
        "reason": action.reason,
        "status": action.status,
        "result": action.result,
        "verification_observation_id": action.verification_observation_id,
        "timestamp": action.timestamp.isoformat(),
    }


def decode_jpeg(data: bytes) -> Optional[np.ndarray]:
    return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)


def create_app(
    detector,
    service: Optional[DossierService] = None,
    conf: float = 0.35,
    images_dir: Optional[Path] = None,
    robot=None,
) -> FastAPI:
    service = service if service is not None else DossierService()
    robot = robot if robot is not None else SimulatedRobot()
    actions = ActionManager(service=service, robot=robot)
    bridge = DossierPerceptionBridge(service=service, detector=detector)
    engine = DiagnosticEngine(service=service, min_confidence=conf)
    tags = PlantTagReader()
    images_dir = Path(images_dir) if images_dir else service.store.file_path.parent / "images"

    # The model and the JSON store are shared by every phone; one call at a time.
    lock = threading.Lock()

    app = FastAPI(title="C.R.A.P live")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/plants")
    def list_plants():
        with lock:
            return [plant_summary(p) for p in service.list_plants()]

    @app.get("/api/plants/{plant_id}")
    def get_plant(plant_id: str):
        with lock:
            try:
                return plant_summary(service.get_plant(plant_id))
            except ValueError:
                raise HTTPException(status_code=404, detail=f"Plant not found: {plant_id}")

    def analyze(frame: np.ndarray) -> dict:
        start = time.perf_counter()
        with lock:
            detections = detector.predict(frame, conf=conf)
        tag = tags.read(frame)
        return {
            "type": "detections",
            "width": int(frame.shape[1]),
            "height": int(frame.shape[0]),
            "infer_ms": round((time.perf_counter() - start) * 1000),
            "detections": [
                {**asdict(d), "bbox": list(d.bbox), "confidence": round(d.confidence, 3)}
                for d in detections
            ],
            "tag": tag,
        }

    @app.websocket("/ws/detect")
    async def detect(websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                data = await websocket.receive_bytes()
                frame = decode_jpeg(data)
                if frame is None:
                    await websocket.send_json({"type": "error", "detail": "Could not decode frame"})
                    continue
                result = await asyncio.to_thread(analyze, frame)
                await websocket.send_json(result)
        except WebSocketDisconnect:
            pass

    def record(plant_id: str, location: str, data: bytes) -> dict:
        frame = decode_jpeg(data)
        if frame is None:
            raise HTTPException(status_code=400, detail="Body must be a JPEG image")

        images_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        image_path = images_dir / f"{plant_id}_{stamp}.jpg"
        cv2.imwrite(str(image_path), frame)

        with lock:
            result = bridge.process_image(
                plant_id=plant_id,
                image_source=image_path,
                location=location,
                conf_threshold=conf,
            )
            observation_id = result["observation"].observation_id
            evaluation = engine.evaluate(plant_id, observation_id)
            verified = actions.link_verification(plant_id, observation_id)
            proposed = actions.propose(plant_id)
            plant = service.get_plant(plant_id)

        return {
            "observation_id": result["observation"].observation_id,
            "image": image_path.name,
            "detections": len(result["detections"]),
            "status": evaluation.plant_status,
            "new_diagnoses": [
                {"condition": d.possible_condition, "status": d.status, "confidence": d.confidence}
                for d in evaluation.diagnoses
            ],
            "notes": evaluation.notes,
            "verified_actions": [action_summary(a) for a in verified],
            "proposed_action": action_summary(proposed) if proposed else None,
            "plant": plant_summary(plant),
        }

    @app.post("/api/plants/{plant_id}/visits")
    async def record_visit(plant_id: str, request: Request, location: str = "field"):
        plant_id = plant_id.strip().upper()
        if not plant_id:
            raise HTTPException(status_code=400, detail="Plant id is required")
        data = await request.body()
        return await asyncio.to_thread(record, plant_id, location, data)

    def change_action(plant_id: str, action_id: str, change) -> dict:
        with lock:
            try:
                action = change(plant_id, action_id)
            except ValueError as err:
                raise HTTPException(status_code=409, detail=str(err))
            return {"action": action_summary(action), "plant": plant_summary(service.get_plant(plant_id))}

    @app.post("/api/plants/{plant_id}/actions/{action_id}/execute")
    async def execute_action(plant_id: str, action_id: str):
        return await asyncio.to_thread(change_action, plant_id, action_id, actions.execute)

    @app.post("/api/plants/{plant_id}/actions/{action_id}/approve")
    def approve_action(plant_id: str, action_id: str):
        return change_action(plant_id, action_id, actions.approve)

    @app.post("/api/plants/{plant_id}/actions/{action_id}/reject")
    def reject_action(plant_id: str, action_id: str):
        return change_action(plant_id, action_id, actions.reject)

    @app.get("/api/robot")
    def robot_status():
        return robot.status()

    # Emergency stop skips the lock so it is never stuck behind other work.
    @app.post("/api/robot/stop")
    def robot_stop():
        try:
            return robot.stop()
        except RobotError as err:
            raise HTTPException(status_code=502, detail=str(err))

    return app
