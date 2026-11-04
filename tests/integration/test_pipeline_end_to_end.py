"""TC-I01..I04: run the real pipeline stages on the committed sample in an isolated workspace.

Each stage runs as a subprocess (exactly like `dvc repro`) with PROJECT_ROOT
pointing at a temporary copy of the repository config and an MLflow file store.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
STAGES = ["ingest", "preprocess", "validate", "split", "train", "evaluate", "register"]


@pytest.fixture(scope="module")
def workspace(tmp_path_factory) -> Path:
    ws = tmp_path_factory.mktemp("ws")
    params = yaml.safe_load((ROOT / "params.yaml").read_text())
    params["ingest"]["source"] = "sample"
    params["preprocess"]["engine"] = "pandas"
    params["validate"].update(min_rows=500, min_rows_per_class=50)
    params["split"]["max_per_class"] = 250
    params["train"].update(max_features=5000, min_df=2, similar_index_size=500)
    params["register"].update(min_macro_f1=0.3, min_priority_recall=0.3, max_priority_flag_rate=1.0)
    (ws / "params.yaml").write_text(yaml.safe_dump(params))
    shutil.copytree(ROOT / "data" / "sample", ws / "data" / "sample")
    shutil.copytree(ROOT / "src", ws / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(ROOT / "requirements", ws / "requirements")
    (ws / "data" / "feedback").mkdir(parents=True)
    # Synced folders (e.g. OneDrive on Windows) can carry a read-only attribute
    # that copytree preserves; make the copy writable so MLflow can clean up.
    for path in ws.rglob("*"):
        path.chmod(0o777 if path.is_dir() else 0o666)
    return ws


def run_stage(ws: Path, stage: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PROJECT_ROOT": str(ws), "PYTHONPATH": str(ws / "src"),
           "MLFLOW_TRACKING_URI": (ws / "mlruns").as_uri(), "PIPELINE_ID": "pytest",
           "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("FEEDBACK_ENCRYPTION_KEY", None)
    return subprocess.run([sys.executable, "-m", f"complaint_router.pipeline.{stage}"], cwd=ws, env=env,
                          capture_output=True, text=True, timeout=600)


def test_full_pipeline_on_sample(workspace):
    for stage in STAGES:
        res = run_stage(workspace, stage)
        assert res.returncode == 0, f"{stage} failed:\n{res.stdout[-3000:]}\n{res.stderr[-3000:]}"

    reports = workspace / "reports"
    metrics = json.loads((reports / "metrics.json").read_text())
    assert metrics["test_macro_f1"] > 0.4                     # 9-class problem, tiny sample
    assert json.loads((reports / "data_validation.json").read_text())["passed"]
    ref = json.loads((reports / "reference_stats.json").read_text())
    assert abs(sum(ref["category_distribution"]) - 1) < 1e-6
    reg = json.loads((reports / "registration.json").read_text())
    assert reg["candidate_version"] == "1" and reg["promoted"] is True


def test_run_log_records_every_stage(workspace):
    lines = (workspace / "reports" / "pipeline_runs.jsonl").read_text().splitlines()
    runs = [json.loads(line) for line in lines]
    assert {r["stage"] for r in runs} >= set(STAGES)
    assert all(r["status"] == "success" for r in runs)
    preprocess = next(r for r in runs if r["stage"] == "preprocess")
    assert preprocess["throughput_rows_per_sec"] > 0


def test_logged_pyfunc_model_serves_predictions(workspace):
    import mlflow.pyfunc
    import pandas as pd

    mlflow.set_tracking_uri((workspace / "mlruns").as_uri())
    run_id = json.loads((workspace / "reports" / "train_run.json").read_text())["mlflow_run_id"]
    model = mlflow.pyfunc.load_model(f"runs:/{run_id}/model")
    out = model.predict(pd.DataFrame({"text": ["My mortgage servicer started foreclosure on my home"],
                                      "top_k_similar": [2]}))
    decision = json.loads(out["result"].iloc[0])
    assert decision["category"] == "mortgage"
    assert len(decision["similar_complaints"]) == 2


def test_second_worse_candidate_is_not_promoted(workspace):
    """Promotion guard: a much weaker retrain must not replace the champion."""
    params = yaml.safe_load((workspace / "params.yaml").read_text())
    params["train"].update(max_features=20, min_df=1)          # deliberately crippled model
    (workspace / "params.yaml").write_text(yaml.safe_dump(params))
    for stage in ("train", "evaluate", "register"):
        assert run_stage(workspace, stage).returncode == 0
    reg = json.loads((workspace / "reports" / "registration.json").read_text())
    assert reg["candidate_version"] == "2"
    assert reg["promoted"] is False and reg["previous_champion"] == "1"


def test_backend_registry_client_reads_real_registry(workspace):
    """Regression: version must be a str and nested autolog runs must be hidden."""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.registry import RegistryClient

    client = RegistryClient((workspace / "mlruns").as_uri(), "complaint-router", "financial-complaint-router")
    champion, changed = client.refresh_champion()
    assert changed and champion["version"] == "1"
    assert client.reference_stats(champion["run_id"])["classes"]
    assert [v["version"] for v in client.list_versions()] == ["2", "1"]
    runs = client.recent_runs()
    assert runs and all(r["run_name"].startswith("train-") for r in runs)
