"""TC-U14..U18: drift statistics."""

import pytest

from complaint_router.monitoring.drift import LENGTH_BINS, distribution, drift_report, histogram, psi

REFERENCE = {
    "classes": ["a", "b", "c"],
    "category_distribution": [0.4, 0.4, 0.2],
    "length_histogram": histogram([150] * 50 + [500] * 50),
    "oov_rate_mean": 0.05,
}


def test_psi_zero_for_identical_distributions():
    assert psi([0.2, 0.3, 0.5], [0.2, 0.3, 0.5]) == pytest.approx(0.0, abs=1e-9)


def test_psi_grows_with_shift():
    assert psi([0.5, 0.5], [0.9, 0.1]) > psi([0.5, 0.5], [0.6, 0.4]) > 0


def test_histogram_and_distribution_normalised():
    assert sum(histogram([10, 120, 5000])) == pytest.approx(1.0)
    assert len(histogram([])) == len(LENGTH_BINS) - 1
    assert distribution(["a", "a", "b"], ["a", "b", "c"]) == pytest.approx([2 / 3, 1 / 3, 0])


def test_no_drift_on_reference_like_traffic():
    cats = ["a"] * 40 + ["b"] * 40 + ["c"] * 20
    rep = drift_report(REFERENCE, cats, [150] * 50 + [500] * 50, [0.05] * 100)
    assert not rep["drift_detected"]
    assert rep["drift_score"] < 0.5


def test_drift_detected_on_new_vocabulary_and_skewed_categories():
    rep = drift_report(REFERENCE, ["c"] * 100, [40] * 100, [0.6] * 100)
    assert rep["drift_detected"]
    assert rep["oov_increase"] > 0.15 and rep["category_psi"] > 0.25
    assert 0.5 <= rep["drift_score"] <= 1.0
