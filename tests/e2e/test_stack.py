"""TC-E01..E06: end-to-end tests against the running docker compose stack.

Prerequisites: `make up && make train`. Run with: pytest tests/e2e -m e2e
"""

from __future__ import annotations

import os

import httpx
import pytest

pytestmark = pytest.mark.e2e
API = os.environ.get("E2E_API", "http://localhost:8000")
UI = os.environ.get("E2E_UI", "http://localhost:8080")
PROM = os.environ.get("E2E_PROMETHEUS", "http://localhost:9090")


def test_frontend_served_and_configured():
    assert "Complaint Router" in httpx.get(UI, timeout=10).text
    assert "APP_CONFIG" in httpx.get(f"{UI}/config.js", timeout=10).text


def test_backend_healthy_with_model():
    body = httpx.get(f"{API}/health", timeout=10).json()
    assert body["status"] == "ok" and body["model_version"]


def test_routing_examples_land_in_expected_teams():
    cases = {
        "My mortgage servicer misapplied my escrow and started foreclosure on my home": "mortgage",
        "A debt collector calls me daily about a debt I do not owe and threatened to sue": "debt_collection",
        "There are accounts on my credit report that are not mine and the bureau will not remove them":
            "credit_reporting",
        "Navient will not put my federal student loans on an income driven repayment plan": "student_loan",
    }
    for text, expected in cases.items():
        r = httpx.post(f"{API}/api/v1/predict", json={"text": text}, timeout=20)
        assert r.status_code == 200
        assert r.json()["category"] == expected, text


def test_severe_complaint_flagged_urgent():
    r = httpx.post(f"{API}/api/v1/predict", timeout=20, json={
        "text": "The servicer refused my payments and scheduled a foreclosure sale of my home next week "
                "even though my loan modification was approved."})
    body = r.json()
    assert body["priority"] == "high"
    assert any("always escalated" in reason for reason in body["priority_reasons"])


def test_latency_under_one_second():
    r = httpx.post(f"{API}/api/v1/predict", json={"text": "The bank charged me overdraft fees twice today"},
                   timeout=20)
    assert r.elapsed.total_seconds() < 1.0


def test_prometheus_scrapes_all_targets():
    targets = httpx.get(f"{PROM}/api/v1/targets", timeout=10).json()["data"]["activeTargets"]
    down = [t["labels"]["job"] for t in targets if t["health"] != "up"]
    assert not down, f"targets down: {down}"
