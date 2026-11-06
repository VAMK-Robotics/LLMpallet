"""FastAPI application: REST API + static frontend.

Run:  python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import rws_client
from .config_store import ROOT, ConfigStore
from .engine import compute_layout, placements_to_csv
from .engine.geometry import PALLET_HEIGHT, PALLET_LENGTH_X, PALLET_WIDTH_Y
from .models import GenerateRequest, PalletParams, RobotSettingsUpdate, normalize_filename

FRONTEND = ROOT / "frontend"
OUTPUT = Path(os.environ.get("LLMPALLET_OUTPUT", ROOT / "output"))

# Controllers use self-signed certificates; the user decides in Settings whether to verify.
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

app = FastAPI(title="LLMpallet", version="1.0")
store = ConfigStore()


@app.get("/api/pallet")
def pallet_info() -> dict:
    return {"length_x": PALLET_LENGTH_X, "width_y": PALLET_WIDTH_Y, "height": PALLET_HEIGHT}


@app.post("/api/layout")
def layout(params: PalletParams) -> dict:
    return compute_layout(params).to_dict()


@app.get("/api/config")
def get_config() -> dict:
    return {"robot": store.public_robot(), "job": store.job.model_dump()}


@app.put("/api/config/robot")
def put_robot(update: RobotSettingsUpdate) -> dict:
    store.update_robot(update)
    return {"robot": store.public_robot()}


@app.put("/api/config/job")
def put_job(job: PalletParams) -> dict:
    store.update_job(job)
    return {"ok": True}


@app.post("/api/test-connection")
def test_connection() -> dict:
    return rws_client.check_connection(store.robot)


@app.post("/api/generate")
def generate(req: GenerateRequest) -> dict:
    params = req.params
    try:
        filename = normalize_filename(req.filename or params.filename or store.robot.default_filename)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    result = compute_layout(params)
    if result.errors:
        return {"ok": False, "filename": filename, "rows": 0, "csv": "",
                "steps": [{"name": "Calculate layout", "ok": False, "message": " ".join(result.errors)}]}

    csv_text = placements_to_csv(result.placements)
    steps = [{"name": "Calculate layout", "ok": True, "message": f"{result.total_boxes} boxes"}]

    try:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / filename).write_text(csv_text, encoding="ascii", newline="\n")
        steps.append({"name": "Save local copy", "ok": True, "message": str(OUTPUT / filename)})
    except OSError as e:
        steps.append({"name": "Save local copy", "ok": False, "message": str(e)})

    store.update_job(params.model_copy(update={"filename": filename}))
    rws = rws_client.send_job(store.robot, filename, csv_text,
                              (params.box_length, params.box_width, params.box_height))
    steps += rws["steps"]
    return {"ok": all(s["ok"] for s in steps), "filename": filename, "rows": result.total_boxes,
            "csv": csv_text, "steps": steps}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")
