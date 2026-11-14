"""Keeps `mlflow models serve` running the current @champion model.

Every few seconds it checks which version is @champion. If it changed (new
model or rollback) or the server died, it restarts the server on that version.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time

from mlflow import MlflowClient
from mlflow.exceptions import MlflowException
from prometheus_client import Counter, Gauge, start_http_server

logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                    format="%(asctime)s | %(levelname)-7s | supervisor | %(message)s")
log = logging.getLogger("supervisor")

MODEL_NAME = os.environ.get("MODEL_NAME", "complaint-router")
ALIAS = os.environ.get("MODEL_ALIAS", "champion")
PORT = os.environ.get("SERVE_PORT", "5001")
WORKERS = os.environ.get("SERVE_WORKERS", "2")
POLL = int(os.environ.get("POLL_SECONDS", "20"))
METRICS_PORT = int(os.environ.get("METRICS_PORT", "9101"))

UP = Gauge("model_server_process_up", "1 if the mlflow scoring process is running")
VERSION = Gauge("model_server_served_version", "Registry version currently served")
RESTARTS = Counter("model_server_restarts_total", "Scoring process (re)starts", ["reason"])
LAST_DEPLOY = Gauge("model_server_last_deploy_timestamp_seconds", "Unix time of last deployment")


def champion_version(client: MlflowClient) -> str | None:
    try:
        return client.get_model_version_by_alias(MODEL_NAME, ALIAS).version
    except MlflowException:
        return None
    except Exception as exc:  # noqa: BLE001 - tracking server may be down/booting
        log.warning("Registry unreachable: %s", exc)
        return None


def start(version: str) -> subprocess.Popen:
    cmd = ["mlflow", "models", "serve", "-m", f"models:/{MODEL_NAME}/{version}", "-h", "0.0.0.0",
           "-p", PORT, "--env-manager", "local", "--workers", WORKERS]
    log.info("Starting scoring server: %s", " ".join(cmd))
    return subprocess.Popen(cmd)


def stop(proc: subprocess.Popen | None) -> None:
    if proc and proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> None:
    start_http_server(METRICS_PORT)
    client = MlflowClient()
    proc: subprocess.Popen | None = None
    served: str | None = None
    running = True

    def _shutdown(*_: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    while running:
        wanted = champion_version(client)
        if wanted is None and served is None:
            log.info("No @%s model registered yet - waiting (train with `make train`)", ALIAS)
        elif wanted is not None and wanted != served:
            reason = "initial" if served is None else "new_champion"
            log.info("Deploying %s v%s (was %s)", MODEL_NAME, wanted, served)
            stop(proc)
            proc, served = start(wanted), wanted
            RESTARTS.labels(reason=reason).inc()
            VERSION.set(float(wanted))
            LAST_DEPLOY.set(time.time())
        elif proc is not None and proc.poll() is not None:
            log.error("Scoring server exited with %s - restarting", proc.returncode)
            proc = start(served)
            RESTARTS.labels(reason="crash").inc()
        UP.set(1 if proc is not None and proc.poll() is None else 0)
        for _ in range(POLL):
            if not running:
                break
            time.sleep(1)
    stop(proc)


if __name__ == "__main__":
    main()
