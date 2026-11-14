"""Data drift checks.

Training saves reference statistics; the backend computes the same statistics
on recent requests and compares them using:
- PSI of the predicted category mix
- PSI of the text length
- increase in out-of-vocabulary words
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

# Text-length buckets (characters of the normalised text).
LENGTH_BINS: tuple[float, ...] = (0, 100, 200, 400, 800, 1600, 3200, float("inf"))
_EPS = 1e-4


def histogram(values: Sequence[float], bins: Sequence[float] = LENGTH_BINS) -> list[float]:
    """Normalised histogram of ``values`` over ``bins`` (fractions summing to 1)."""
    if len(values) == 0:
        return [0.0] * (len(bins) - 1)
    counts, _ = np.histogram(np.asarray(values, dtype=float), bins=np.asarray(bins, dtype=float))
    return (counts / counts.sum()).tolist()


def distribution(labels: Sequence[str], classes: Sequence[str]) -> list[float]:
    """Fraction of each class in ``labels`` (ordered like ``classes``)."""
    if len(labels) == 0:
        return [0.0] * len(classes)
    labels = list(labels)
    return [labels.count(c) / len(labels) for c in classes]


def psi(expected: Sequence[float], actual: Sequence[float]) -> float:
    """Population Stability Index (< 0.1 stable, > 0.25 big shift)."""
    e = np.clip(np.asarray(expected, dtype=float), _EPS, None)
    a = np.clip(np.asarray(actual, dtype=float), _EPS, None)
    e, a = e / e.sum(), a / a.sum()
    return float(np.sum((a - e) * np.log(a / e)))


def drift_report(reference: dict, live_categories: Sequence[str], live_lengths: Sequence[float],
                 live_oov: Sequence[float], psi_threshold: float = 0.25,
                 oov_increase_threshold: float = 0.15) -> dict:
    """Compare live statistics with the reference and decide whether drift occurred."""
    classes = reference["classes"]
    category_psi = psi(reference["category_distribution"], distribution(live_categories, classes))
    length_psi = psi(reference["length_histogram"], histogram(live_lengths))
    live_oov_mean = float(np.mean(live_oov)) if len(live_oov) else 0.0
    oov_increase = max(0.0, live_oov_mean - float(reference["oov_rate_mean"]))
    # 0..1 score for the dashboard: 0.5 means the worst signal is at its threshold.
    score = min(1.0, max(category_psi / psi_threshold, length_psi / psi_threshold,
                         oov_increase / oov_increase_threshold) / 2)
    return {
        "category_psi": round(category_psi, 4),
        "length_psi": round(length_psi, 4),
        "oov_rate_live": round(live_oov_mean, 4),
        "oov_rate_reference": round(float(reference["oov_rate_mean"]), 4),
        "oov_increase": round(oov_increase, 4),
        "drift_score": round(float(score), 4),
        "drift_detected": bool(category_psi > psi_threshold or length_psi > psi_threshold
                               or oov_increase > oov_increase_threshold),
    }
