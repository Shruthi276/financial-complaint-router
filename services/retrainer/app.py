"""Retrainer service: runs `dvc repro --force` when
  - Alertmanager sends a DataDriftDetected alert (POST /webhook/alertmanager), or
  - an admin clicks retrain in the UI (POST /retrain).
Only one run at a time, with a cool-down so one alert can't start many runs.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                    format="%(asctime)s | %(levelname)-7s | retrainer | %(message)s")
log = logging.getLogger("retrainer")

WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
COOLDOWN = int(os.environ.get("RETRAIN_COOLDOWN_SECONDS", "1800"))
COMMAND = os.environ.get("RETRAIN_COMMAND", "dvc repro --force")
HISTORY = WORKSPACE / "reports" / "retrain_history.jsonl"
LOG_DIR = WORKSPACE / "logs" / "retrain"

RUNS = Counter("retrainer_runs_total", "Retraining runs", ["trigger", "status"])
SKIPPED = Counter("retrainer_skipped_total", "Triggers ignored", ["reason"])
IN_PROGRESS = Gauge("retrainer_in_progress", "1 while a retraining run is executing")
LAST_DURATION = Gauge("retrainer_last_duration_seconds", "Duration of the last retraining run")
LAST_SUCCESS = Gauge("retrainer_last_success_timestamp_seconds", "Unix time of last successful retrain")

_lock = threading.Lock()
_state: dict = {"running": False, "current": None, "last": None, "last_finished_at": 0.0}


class RetrainRequest(BaseModel):
    reason: str = "manual"
    trigger: str = "manual"


def _record(entry: dict) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def _run(job: dict) -> None:
    """Run the DVC pipeline in a background thread and save the result."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{job['id']}.log"
    env = {**os.environ, "PIPELINE_ID": job["id"], "TRAIN_TRIGGER": job["trigger"]}
    start = time.time()
    IN_PROGRESS.set(1)
    try:
        with log_path.open("w", encoding="utf-8") as out:
            rc = subprocess.call(COMMAND.split(), cwd=WORKSPACE, env=env, stdout=out, stderr=subprocess.STDOUT)
        status = "success" if rc == 0 else "failed"
    except OSError as exc:
        log.exception("Could not start pipeline")
        status, rc = "failed", -1
        log_path.write_text(str(exc))
    duration = time.time() - start
    registration = {}
    reg_file = WORKSPACE / "reports" / "registration.json"
    if status == "success" and reg_file.exists():
        registration = json.loads(reg_file.read_text())
    job.update({"status": status, "return_code": rc, "duration_seconds": round(duration, 1),
                "finished_at": datetime.now(timezone.utc).isoformat(), "log_file": str(log_path),
                "promoted": registration.get("promoted"), "version": registration.get("candidate_version")})
    RUNS.labels(trigger=job["trigger"], status=status).inc()
    LAST_DURATION.set(duration)
    if status == "success":
        LAST_SUCCESS.set(time.time())
    IN_PROGRESS.set(0)
    _record(job)
    log.info("Retrain %s finished: %s in %.0fs (promoted=%s)", job["id"], status, duration, job["promoted"])
    with _lock:
        _state.update(running=False, current=None, last=job, last_finished_at=time.time())


def launch(trigger: str, reason: str, respect_cooldown: bool) -> dict:
    """Start a retraining run unless one is running or we are inside the cool-down."""
    with _lock:
        if _state["running"]:
            SKIPPED.labels(reason="already_running").inc()
            return {"accepted": False, "message": "A retraining run is already in progress",
                    "current": _state["current"]}
        wait = COOLDOWN - (time.time() - _state["last_finished_at"])
        if respect_cooldown and _state["last_finished_at"] and wait > 0:
            SKIPPED.labels(reason="cooldown").inc()
            return {"accepted": False, "message": f"Cool-down active, next automatic retrain in {int(wait)}s"}
        job = {"id": f"retrain-{uuid.uuid4().hex[:8]}", "trigger": trigger, "reason": reason,
               "started_at": datetime.now(timezone.utc).isoformat(), "status": "running"}
        _state.update(running=True, current=job)
    threading.Thread(target=_run, args=(job,), daemon=True).start()
    log.info("Retrain %s started (trigger=%s, reason=%s)", job["id"], trigger, reason)
    return {"accepted": True, "message": "Retraining started", "job": job}


app = FastAPI(title="Complaint Router Retrainer", version="1.0.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "running": _state["running"]}


@app.get("/status")
def status_() -> dict:
    history = []
    if HISTORY.exists():
        history = [json.loads(line) for line in HISTORY.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {"running": _state["running"], "current": _state["current"], "cooldown_seconds": COOLDOWN,
            "history": list(reversed(history[-20:]))}


@app.post("/retrain")
def retrain(req: RetrainRequest, x_admin_token: str = Header("", alias="X-Admin-Token")) -> dict:
    if not ADMIN_TOKEN or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "Invalid or missing admin token")
    return launch(req.trigger or "manual", req.reason, respect_cooldown=False)


@app.post("/webhook/alertmanager")
async def alertmanager_webhook(request: Request) -> dict:
    """Alertmanager webhook payload (version 4). Only firing retrain-alerts trigger a run."""
    payload = await request.json()
    firing = [a for a in payload.get("alerts", [])
              if a.get("status") == "firing" and a.get("labels", {}).get("action") == "retrain"]
    if not firing:
        return {"accepted": False, "message": "no firing retrain alerts"}
    names = sorted({a["labels"].get("alertname", "?") for a in firing})
    return launch("drift_alert", "Alertmanager: " + ", ".join(names), respect_cooldown=True)


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
