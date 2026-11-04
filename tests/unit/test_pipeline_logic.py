"""TC-U28..U36: pure logic of pipeline stages (validation, split, promotion, run log, feedback)."""

import pandas as pd
import pytest
from cryptography.fernet import Fernet

from complaint_router import feedback
from complaint_router.pipeline import run_log
from complaint_router.pipeline.register import decide
from complaint_router.pipeline.split import balanced_sample, split
from complaint_router.pipeline.validate import run_checks

VALIDATE_CFG = {"min_rows": 10, "max_null_fraction": 0.0, "min_classes": 3, "min_rows_per_class": 5}
REGISTER_CFG = {"min_macro_f1": 0.7, "min_priority_recall": 0.7, "max_regression": 0.005,
                "max_priority_flag_rate": 0.35}


def test_validation_passes_on_good_data(corpus):
    assert all(c["passed"] for c in run_checks(corpus, VALIDATE_CFG))


def test_validation_fails_on_unknown_label_and_missing_column(corpus):
    bad = corpus.copy()
    bad.loc[0, "category"] = "crypto_scam"
    assert not next(c for c in run_checks(bad, VALIDATE_CFG) if c["check"] == "label_domain")["passed"]
    checks = run_checks(corpus.drop(columns=["priority"]), VALIDATE_CFG)
    assert not next(c for c in checks if c["check"] == "schema")["passed"]


def test_balanced_sample_caps_and_drops(corpus):
    small = corpus[corpus["category"] != "mortgage"]
    tiny = corpus[corpus["category"] == "mortgage"].head(3)
    df = balanced_sample(pd.concat([small, tiny]), max_per_class=10, min_per_class=5, seed=1)
    assert df["category"].value_counts().max() == 10
    assert "mortgage" not in set(df["category"])


def test_split_is_stratified_and_disjoint(corpus):
    train, val, test = split(corpus, 0.2, 0.2, seed=3)
    assert len(train) + len(val) + len(test) == len(corpus)
    assert set(train["complaint_id"]).isdisjoint(test["complaint_id"])
    assert set(test["category"]) == set(corpus["category"])


@pytest.mark.parametrize("metrics,champion,expected", [
    ({"test_macro_f1": 0.82, "test_priority_recall": 0.8}, None, True),
    ({"test_macro_f1": 0.65, "test_priority_recall": 0.8}, None, False),       # below absolute bar
    ({"test_macro_f1": 0.82, "test_priority_recall": 0.5}, None, False),       # misses urgent cases
    ({"test_macro_f1": 0.80, "test_priority_recall": 0.8}, 0.84, False),       # regression vs champion
    ({"test_macro_f1": 0.838, "test_priority_recall": 0.8}, 0.84, True),       # within tolerance
    ({"test_macro_f1": 0.82, "test_priority_recall": 0.9, "test_priority_flag_rate": 0.6}, None, False),  # flags all
])
def test_promotion_gate(metrics, champion, expected):
    promote, reasons = decide(metrics, champion, REGISTER_CFG)
    assert promote is expected and reasons


def test_stage_run_logs_success_and_failure(tmp_path, monkeypatch):
    log = tmp_path / "runs.jsonl"
    monkeypatch.setattr(run_log, "RUN_LOG_PATH", log)
    with run_log.stage_run("demo") as r:
        r.rows_in = 100
    with pytest.raises(ValueError), run_log.stage_run("demo"):
        raise ValueError("boom")
    rows = run_log.read_runs()
    assert [r["status"] for r in rows] == ["success", "failed"]
    assert rows[1]["error"] == "ValueError: boom"
    assert rows[0]["rows_in"] == 100


def test_feedback_is_encrypted_and_reloadable(tmp_path, monkeypatch):
    monkeypatch.setenv("FEEDBACK_ENCRYPTION_KEY", Fernet.generate_key().decode())
    feedback.append_feedback(tmp_path, {"complaint_text": "The collector harassed me about a debt I never had",
                                        "correct_category": "debt_collection", "correct_priority": "high"})
    raw = (tmp_path / feedback.FEEDBACK_FILE).read_text()
    assert "collector" not in raw                      # encrypted at rest
    df = feedback.load_feedback_examples(tmp_path)
    assert df["category"].tolist() == ["debt_collection"] and df["priority"].tolist() == [1]


def test_feedback_refused_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("FEEDBACK_ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError):
        feedback.append_feedback(tmp_path, {"complaint_text": "x"})
