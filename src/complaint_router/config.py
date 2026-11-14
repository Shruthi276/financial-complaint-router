"""Configuration helpers: locate the project root and load ``params.yaml``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# src/complaint_router/config.py -> project root is two levels above "src".
PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parents[2]))


def load_params(path: str | Path | None = None) -> dict[str, Any]:
    """Load params.yaml (or the given file) as a dict."""
    params_path = Path(path) if path else PROJECT_ROOT / "params.yaml"
    if not params_path.exists():
        raise FileNotFoundError(f"Parameter file not found: {params_path}")
    with params_path.open("r", encoding="utf-8") as fh:
        params = yaml.safe_load(fh)
    if not isinstance(params, dict):
        raise ValueError(f"{params_path} must contain a YAML mapping")
    return params


def project_path(*parts: str) -> Path:
    """Return an absolute path inside the project root."""
    return PROJECT_ROOT.joinpath(*parts)


def mlflow_tracking_uri() -> str:
    """MLflow tracking server URI (overridable through ``MLFLOW_TRACKING_URI``)."""
    return os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")
