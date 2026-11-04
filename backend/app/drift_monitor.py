"""Online drift monitor: rolling window of live predictions vs. training reference."""

from __future__ import annotations

import threading
from collections import deque

from app import metrics as m
from complaint_router.monitoring.drift import drift_report


class DriftMonitor:
    """Thread-safe rolling window. ``observe`` after each prediction, ``report`` any time."""

    def __init__(self, window: int, min_samples: int, psi_threshold: float, oov_threshold: float) -> None:
        self.window = window
        self.min_samples = min_samples
        self.psi_threshold = psi_threshold
        self.oov_threshold = oov_threshold
        self._lock = threading.Lock()
        self._categories: deque[str] = deque(maxlen=window)
        self._lengths: deque[int] = deque(maxlen=window)
        self._oov: deque[float] = deque(maxlen=window)
        self.reference: dict | None = None
        self.last_report: dict = {}

    def set_reference(self, reference: dict | None) -> None:
        """Install new reference statistics (new champion) and clear the window."""
        with self._lock:
            self.reference = reference
            self._categories.clear()
            self._lengths.clear()
            self._oov.clear()
        self._publish(self._empty_report("reference updated, window reset"))

    def observe(self, category: str, n_chars: int, oov_rate: float) -> None:
        with self._lock:
            self._categories.append(category)
            self._lengths.append(n_chars)
            self._oov.append(oov_rate)

    def _empty_report(self, status: str) -> dict:
        return {"status": status, "window_size": len(self._categories), "min_samples": self.min_samples,
                "drift_detected": False, "drift_score": 0.0}

    def report(self) -> dict:
        """Compute (and export to Prometheus) the current drift report."""
        with self._lock:
            n = len(self._categories)
            if self.reference is None:
                rep = self._empty_report("no reference statistics (model not trained yet)")
            elif n < self.min_samples:
                rep = self._empty_report(f"collecting samples ({n}/{self.min_samples})")
            else:
                rep = drift_report(self.reference, list(self._categories), list(self._lengths), list(self._oov),
                                   self.psi_threshold, self.oov_threshold)
                rep.update({"status": "drift" if rep["drift_detected"] else "stable", "window_size": n,
                            "min_samples": self.min_samples})
        self._publish(rep)
        return rep

    def _publish(self, rep: dict) -> None:
        self.last_report = rep
        m.DRIFT_WINDOW.set(rep.get("window_size", 0))
        m.DRIFT_SCORE.set(rep.get("drift_score", 0.0))
        m.DRIFT_DETECTED.set(1 if rep.get("drift_detected") else 0)
        m.DRIFT_CATEGORY_PSI.set(rep.get("category_psi", 0.0))
        m.DRIFT_LENGTH_PSI.set(rep.get("length_psi", 0.0))
        m.DRIFT_OOV.set(rep.get("oov_rate_live", 0.0))
        m.DRIFT_OOV_INCREASE.set(rep.get("oov_increase", 0.0))
