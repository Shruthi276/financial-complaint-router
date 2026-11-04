"""Stage run bookkeeping for the pipeline management console.

Every stage executes inside :func:`stage_run`, which appends one JSON line to
``reports/pipeline_runs.jsonl`` with status, duration, row counts, throughput,
git commit and (on failure) the error. The backend reads this file to show
successes/failures and to export pipeline metrics to Prometheus.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import traceback
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from complaint_router.config import project_path
from complaint_router.logging_utils import get_logger

logger = get_logger(__name__)
RUN_LOG_PATH = Path(os.environ.get("PIPELINE_RUN_LOG", project_path("reports", "pipeline_runs.jsonl")))


def git_commit() -> str:
    """Current git commit hash, or 'unknown' outside a repository."""
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project_path(),
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


@dataclass
class StageRun:
    """Mutable record filled in by a stage while it runs."""

    stage: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    pipeline_id: str = field(default_factory=lambda: os.environ.get("PIPELINE_ID", "manual"))
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    status: str = "running"
    duration_seconds: float = 0.0
    rows_in: int = 0
    rows_out: int = 0
    throughput_rows_per_sec: float = 0.0
    git_commit: str = field(default_factory=git_commit)
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _append(record: StageRun, path: Path | None = None) -> None:
    path = path or RUN_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(record)) + "\n")


@contextmanager
def stage_run(stage: str) -> Iterator[StageRun]:
    """Time a stage and persist its outcome, re-raising any error after logging it."""
    run = StageRun(stage=stage)
    logger.info("Stage %s started (run %s)", stage, run.run_id)
    start = time.perf_counter()
    try:
        yield run
        run.status = "success"
    except Exception as exc:
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        logger.error("Stage %s failed: %s\n%s", stage, run.error, traceback.format_exc())
        raise
    finally:
        run.duration_seconds = round(time.perf_counter() - start, 3)
        run.finished_at = datetime.now(timezone.utc).isoformat()
        rows = run.rows_in or run.rows_out
        if run.duration_seconds > 0 and rows:
            run.throughput_rows_per_sec = round(rows / run.duration_seconds, 1)
        _append(run)
        logger.info("Stage %s %s in %.2fs (in=%d out=%d, %.0f rows/s)", stage, run.status,
                    run.duration_seconds, run.rows_in, run.rows_out, run.throughput_rows_per_sec)


def read_runs(path: Path | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    """Read stage runs (most recent last). Corrupt lines are skipped."""
    path = path or RUN_LOG_PATH
    if not path.exists():
        return []
    runs = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                runs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return runs[-limit:] if limit else runs


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    """Write a JSON report, creating parent folders."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
