"""Reads the MLflow model registry: current champion version, its drift
reference statistics, and the list of versions/runs for the UI."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from app.metrics import MODEL_VERSION

logger = logging.getLogger(__name__)


class RegistryClient:
    """Small wrapper around MlflowClient that never crashes the API."""

    def __init__(self, tracking_uri: str, model_name: str, experiment_name: str) -> None:
        self.tracking_uri = tracking_uri
        self.model_name = model_name
        self.experiment_name = experiment_name
        self.champion: dict[str, Any] | None = None

    def _client(self):  # noqa: ANN202 - lazy import keeps app start-up fast
        from mlflow import MlflowClient

        return MlflowClient(tracking_uri=self.tracking_uri)

    def available(self) -> bool:
        try:
            self._client().search_experiments(max_results=1)
            return True
        except Exception:  # noqa: BLE001 - any failure means "down"
            return False

    def refresh_champion(self) -> tuple[dict[str, Any] | None, bool]:
        """Fetch @champion. Returns (champion_info, changed_since_last_call)."""
        try:
            mv = self._client().get_model_version_by_alias(self.model_name, "champion")
        except Exception as exc:  # noqa: BLE001
            logger.debug("No champion available: %s", exc)
            return self.champion, False
        version = str(mv.version)  # the file store returns int, the REST store str
        changed = self.champion is None or self.champion["version"] != version
        if changed:
            run = self._client().get_run(mv.run_id)
            self.champion = {"version": version, "run_id": mv.run_id,
                             "created": mv.creation_timestamp, "metrics": run.data.metrics,
                             "params": {k: v for k, v in run.data.params.items() if k.startswith("train.")},
                             "git_commit": run.data.tags.get("git_commit")}
            MODEL_VERSION.set(float(version))
            logger.info("Champion is now %s v%s (run %s)", self.model_name, version, mv.run_id)
        return self.champion, changed

    def reference_stats(self, run_id: str) -> dict | None:
        """Download ``evaluation/reference_stats.json`` from the run's artifacts."""
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = self._client().download_artifacts(run_id, "evaluation/reference_stats.json", tmp)
                return json.loads(Path(path).read_text())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not fetch reference stats for run %s: %s", run_id, exc)
            return None

    def list_versions(self) -> list[dict[str, Any]]:
        try:
            client = self._client()
            versions = client.search_model_versions(f"name='{self.model_name}'")
            aliases = {}
            for alias, ver in client.get_registered_model(self.model_name).aliases.items():
                aliases.setdefault(str(ver), []).append(alias)
        except Exception:  # noqa: BLE001
            return []
        return sorted([{"version": str(v.version), "run_id": v.run_id, "created": v.creation_timestamp,
                        "status": v.status, "aliases": aliases.get(str(v.version), []),
                        "test_macro_f1": v.tags.get("test_macro_f1"), "gate": v.tags.get("gate")}
                       for v in versions], key=lambda d: int(d["version"]), reverse=True)

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            client = self._client()
            exp = client.get_experiment_by_name(self.experiment_name)
            if exp is None:
                return []
            # Nested (autolog) runs are hidden; MLflow 2.x has no "IS NULL" filter, so filter here.
            runs = [r for r in client.search_runs([exp.experiment_id], order_by=["attributes.start_time DESC"],
                                                  max_results=limit * 3)
                    if "mlflow.parentRunId" not in r.data.tags][:limit]
        except Exception:  # noqa: BLE001
            return []
        return [{"run_id": r.info.run_id, "experiment_id": r.info.experiment_id, "run_name": r.info.run_name,
                 "status": r.info.status,
                 "start_time": r.info.start_time, "end_time": r.info.end_time,
                 "val_macro_f1": r.data.metrics.get("val_macro_f1"),
                 "test_macro_f1": r.data.metrics.get("test_macro_f1"),
                 "model_type": r.data.params.get("train.model_type"),
                 "trigger": r.data.tags.get("trigger"), "git_commit": r.data.tags.get("git_commit")}
                for r in runs]
