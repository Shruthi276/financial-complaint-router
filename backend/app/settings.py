"""Backend configuration, read once from environment variables (12-factor style)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_list(name: str, default: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    """All tunables of the backend service. Every value can be overridden via env."""

    model_server_url: str = field(default_factory=lambda: os.environ.get("MODEL_SERVER_URL", "http://localhost:5001"))
    model_timeout_seconds: float = field(default_factory=lambda: float(os.environ.get("MODEL_TIMEOUT_SECONDS", "15")))
    mlflow_tracking_uri: str = field(default_factory=lambda: os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000"))
    model_name: str = field(default_factory=lambda: os.environ.get("MODEL_NAME", "complaint-router"))
    experiment_name: str = field(
        default_factory=lambda: os.environ.get("MLFLOW_EXPERIMENT", "financial-complaint-router"))
    retrainer_url: str = field(default_factory=lambda: os.environ.get("RETRAINER_URL", "http://localhost:8001"))
    admin_token: str = field(default_factory=lambda: os.environ.get("ADMIN_TOKEN", ""))
    workspace_dir: Path = field(default_factory=lambda: Path(os.environ.get("WORKSPACE_DIR", ".")))
    cors_origins: list[str] = field(default_factory=lambda: _env_list("CORS_ORIGINS", "*"))
    registry_poll_seconds: int = field(default_factory=lambda: int(os.environ.get("REGISTRY_POLL_SECONDS", "30")))
    drift_window: int = field(default_factory=lambda: int(os.environ.get("DRIFT_WINDOW", "200")))
    drift_min_samples: int = field(default_factory=lambda: int(os.environ.get("DRIFT_MIN_SAMPLES", "50")))
    drift_psi_threshold: float = field(default_factory=lambda: float(os.environ.get("DRIFT_PSI_THRESHOLD", "0.25")))
    drift_oov_threshold: float = field(default_factory=lambda: float(os.environ.get("DRIFT_OOV_THRESHOLD", "0.15")))
    min_text_chars: int = 20
    max_text_chars: int = 10000
    max_batch: int = 50

    @property
    def reports_dir(self) -> Path:
        return self.workspace_dir / "reports"

    @property
    def feedback_dir(self) -> Path:
        return self.workspace_dir / "data" / "feedback"

    @property
    def dvc_yaml(self) -> Path:
        return self.workspace_dir / "dvc.yaml"
