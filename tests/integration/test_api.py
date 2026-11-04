"""TC-I05..I16: backend REST API contract, with the model server and registry replaced by fakes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.main import create_app  # noqa: E402
from app.model_client import ModelUnavailableError  # noqa: E402
from app.settings import Settings  # noqa: E402

ADMIN = "test-admin-token"


class FakeModel:
    """Stands in for the MLflow model server; delegates to a real fitted router."""

    def __init__(self, router) -> None:
        self.router = router
        self.up = True

    async def ping(self) -> bool:
        return self.up

    async def predict(self, texts, top_k_similar=3):
        if not self.up:
            raise ModelUnavailableError("down")
        return self.router.predict(texts, top_k_similar=top_k_similar)

    async def close(self) -> None:
        pass


class FakeRegistry:
    def __init__(self) -> None:
        self.champion = {"version": "3", "run_id": "abc", "metrics": {}, "params": {}, "git_commit": "deadbee"}

    def available(self):
        return True

    def refresh_champion(self):
        return self.champion, False

    def reference_stats(self, run_id):
        return None

    def list_versions(self):
        return [{"version": "3", "aliases": ["champion"]}]

    def recent_runs(self, limit=20):
        return []


@pytest.fixture()
def workspace(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "pipeline_runs.jsonl").write_text(
        json.dumps({"stage": "ingest", "status": "success", "duration_seconds": 2.0,
                    "throughput_rows_per_sec": 500, "finished_at": "2026-01-01T00:00:00+00:00"}) + "\n" +
        json.dumps({"stage": "train", "status": "failed", "error": "boom", "duration_seconds": 1.0,
                    "finished_at": "2026-01-01T00:01:00+00:00"}) + "\n")
    (tmp_path / "reports" / "metrics.json").write_text(json.dumps({"test_macro_f1": 0.8}))
    (tmp_path / "dvc.yaml").write_text((Path(__file__).resolve().parents[2] / "dvc.yaml").read_text(encoding="utf-8"))
    return tmp_path


@pytest.fixture()
def client(fitted_router, workspace, monkeypatch):
    monkeypatch.setenv("FEEDBACK_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN)
    monkeypatch.setenv("WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("DRIFT_MIN_SAMPLES", "5")
    fake = FakeModel(fitted_router)
    app = create_app(Settings(), model_client=fake, registry=FakeRegistry(), start_background=False)
    with TestClient(app) as c:
        c.fake_model = fake
        yield c


def test_health_ok(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["model_server"] == "up" and body["model_version"] == "3"


def test_health_degraded_when_model_down(client):
    client.fake_model.up = False
    assert client.get("/health").json()["status"] == "degraded"


def test_predict_contract(client):
    text = "The debt collector threatened to sue me over a debt I never owed"
    r = client.post("/api/v1/predict", json={"text": text})
    assert r.status_code == 200
    body = r.json()
    assert body["category"] == "debt_collection"
    assert body["model_version"] == "3" and len(body["prediction_id"]) == 32
    assert body["priority"] in ("high", "normal")


@pytest.mark.parametrize("payload", [
    {"text": "too short"}, {"text": "1234567890 1234567890 !!!"}, {}, {"text": "x" * 10001},
    {"text": "valid complaint text here ok", "top_k_similar": 50},
])
def test_predict_rejects_invalid_input(client, payload):
    assert client.post("/api/v1/predict", json=payload).status_code == 422


def test_predict_returns_503_when_model_unavailable(client):
    client.fake_model.up = False
    r = client.post("/api/v1/predict", json={"text": "My checking account was charged overdraft fees twice"})
    assert r.status_code == 503 and "not available" in r.json()["detail"]


def test_batch_predict_and_limit(client):
    texts = ["my credit report shows an account that is not mine"] * 3
    assert len(client.post("/api/v1/predict/batch", json={"texts": texts}).json()["results"]) == 3
    assert client.post("/api/v1/predict/batch", json={"texts": texts * 20}).status_code == 422


def test_feedback_stored_encrypted(client, workspace):
    r = client.post("/api/v1/feedback", json={
        "prediction_id": "x", "complaint_text": "The bank charged me overdraft fees on my checking account",
        "predicted_category": "credit_card", "correct_category": "bank_account"})
    assert r.status_code == 200 and r.json()["stored"]
    stored = (workspace / "data" / "feedback" / "feedback.enc.jsonl").read_text()
    assert "overdraft" not in stored


def test_feedback_rejects_unknown_category(client):
    r = client.post("/api/v1/feedback", json={"prediction_id": "x", "complaint_text": "a" * 30,
                                              "predicted_category": "mortgage", "correct_category": "crypto"})
    assert r.status_code == 422


def test_categories_and_examples(client):
    assert len(client.get("/api/v1/categories").json()) == 9
    assert len(client.get("/api/v1/examples").json()) >= 3


def test_pipeline_endpoints(client):
    dag = client.get("/api/v1/pipeline/dag").json()
    ids = {n["id"] for n in dag["nodes"]}
    assert {"ingest", "preprocess", "train", "register"} <= ids
    assert {"source": "ingest", "target": "preprocess"} in dag["edges"]
    assert {"source": "train", "target": "evaluate"} in dag["edges"]
    runs = client.get("/api/v1/pipeline/runs").json()
    assert runs["summary"]["failed"] == 1 and runs["runs"][0]["stage"] == "train"
    assert client.get("/api/v1/pipeline/reports").json()["metrics"]["test_macro_f1"] == 0.8


def test_retrain_requires_admin_token(client):
    assert client.post("/api/v1/pipeline/retrain", json={"reason": "x"}).status_code == 401
    assert client.post("/api/v1/pipeline/retrain", json={"reason": "x"},
                       headers={"X-Admin-Token": "wrong"}).status_code == 401


def test_drift_endpoint_reports_collecting_then_stable(client):
    assert "no reference" in client.get("/api/v1/monitoring/drift").json()["status"]


def test_metrics_exposed(client):
    client.post("/api/v1/predict", json={"text": "unauthorized charges on my credit card statement"})
    text = client.get("/metrics").text
    for name in ("complaint_router_predictions_total", "complaint_router_http_request_duration_seconds",
                 "complaint_router_drift_score", "complaint_router_pipeline_stage_last_duration_seconds",
                 "complaint_router_offline_metric"):
        assert name in text
