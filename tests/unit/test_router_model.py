"""TC-U19..U27: ComplaintRouter behaviour."""

import pytest

from complaint_router.model.router_model import ComplaintRouter, RouterConfig


def test_predicts_expected_categories(fitted_router):
    out = fitted_router.predict([
        "The debt collector keeps calling about a debt I do not owe",
        "My mortgage escrow payment was misapplied by the servicer",
    ])
    assert [o["category"] for o in out] == ["debt_collection", "mortgage"]


def test_output_contract(fitted_router):
    o = fitted_router.predict(["Unauthorized charges on my credit card were not refunded"], top_k_similar=2)[0]
    for key in ("category", "category_label", "team", "confidence", "low_confidence", "alternatives",
                "priority", "priority_score", "priority_reasons", "explanation", "similar_complaints", "text_stats"):
        assert key in o
    assert 0 <= o["confidence"] <= 1
    assert o["priority"] in ("high", "normal")
    assert len(o["alternatives"]) == 3
    assert abs(sum(a["probability"] for a in o["alternatives"])) <= 1.0001
    assert len(o["similar_complaints"]) == 2
    assert o["similar_complaints"][0]["similarity"] >= o["similar_complaints"][1]["similarity"]


def test_explanation_terms_relate_to_text(fitted_router):
    o = fitted_router.predict(["the bank charged overdraft fees on my checking account"])[0]
    terms = " ".join(t["term"] for t in o["explanation"])
    assert any(w in terms for w in ("overdraft", "checking", "bank"))


def test_severe_keywords_always_escalate(fitted_router):
    o = fitted_router.predict(["Fraud: unauthorized charges and they threatened foreclosure"])[0]
    assert any("always escalated: foreclosure" in r for r in o["priority_reasons"])
    assert any("signals mentioned: fraud" in r for r in o["priority_reasons"])
    assert o["priority"] == "high"


def test_priority_decision_rule(fitted_router):
    t = fitted_router.priority_threshold
    assert fitted_router.priority_decision(0.0, ["foreclosure"])
    assert not fitted_router.priority_decision(0.0, ["fraud"])          # soft signal alone is not enough
    assert fitted_router.priority_decision(t, [])
    assert not fitted_router.priority_decision(max(0.0, t - 0.01), [])


def test_priority_threshold_tuned_in_range(fitted_router):
    assert 0.05 <= fitted_router.priority_threshold <= 0.95


def test_oov_rate(fitted_router):
    assert fitted_router.oov_rate("") == 1.0
    assert fitted_router.oov_rate("zzqx blorf") == 1.0
    assert fitted_router.oov_rate("credit report") == 0.0


def test_save_load_roundtrip(fitted_router, tmp_path):
    path = tmp_path / "router.joblib"
    fitted_router.save(str(path))
    loaded = ComplaintRouter.load(str(path))
    text = ["the collection agency threatened to sue me"]
    assert loaded.predict(text)[0]["category"] == fitted_router.predict(text)[0]["category"]
    assert loaded.priority_threshold == fitted_router.priority_threshold


@pytest.mark.parametrize("model_type", ["sgd", "cnb"])
def test_alternative_model_types(corpus, model_type):
    cfg = RouterConfig(model_type=model_type, min_df=1, similar_index_size=50)
    router = ComplaintRouter(cfg).fit(corpus["text"], corpus["category"], corpus["priority"])
    assert router.predict(["my credit report has incorrect information"])[0]["category"] == "credit_reporting"


def test_invalid_usage():
    with pytest.raises(ValueError):
        ComplaintRouter(RouterConfig(model_type="bert"))
    with pytest.raises(RuntimeError):
        ComplaintRouter().predict(["text"])
