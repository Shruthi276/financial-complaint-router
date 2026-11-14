"""Prometheus metrics of the backend (GET /metrics):
API requests and latency, predictions and confidence, drift, pipeline stages."""

from __future__ import annotations

import json
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from prometheus_client import Counter, Gauge, Histogram
from prometheus_client.core import REGISTRY, GaugeMetricFamily

NS = "complaint_router"

HTTP_REQUESTS = Counter(f"{NS}_http_requests_total", "HTTP requests", ["method", "endpoint", "status"])
HTTP_LATENCY = Histogram(f"{NS}_http_request_duration_seconds", "End-to-end API latency", ["endpoint"],
                         buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))
MODEL_LATENCY = Histogram(f"{NS}_model_inference_duration_seconds", "Latency of the model server call",
                          buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5))
MODEL_ERRORS = Counter(f"{NS}_model_errors_total", "Failed model server calls", ["type"])
MODEL_SERVER_UP = Gauge(f"{NS}_model_server_up", "1 if the model server answers /ping")
MODEL_VERSION = Gauge(f"{NS}_champion_model_version", "Registry version of the @champion model")

PREDICTIONS = Counter(f"{NS}_predictions_total", "Routing decisions", ["category", "priority"])
CONFIDENCE = Histogram(f"{NS}_prediction_confidence", "Top-class probability",
                       buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0))
PRIORITY_SCORE = Histogram(f"{NS}_priority_score", "Priority model score",
                           buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0))
LOW_CONFIDENCE = Counter(f"{NS}_low_confidence_predictions_total", "Predictions below the confidence bar")
TEXT_LENGTH = Histogram(f"{NS}_input_text_chars", "Length of incoming complaints (chars)",
                        buckets=(50, 100, 200, 400, 800, 1600, 3200, 6400))
FEEDBACK = Counter(f"{NS}_feedback_total", "Agent feedback", ["outcome"])

DRIFT_SCORE = Gauge(f"{NS}_drift_score", "Composite drift score (>=0.5 means a threshold is crossed)")
DRIFT_DETECTED = Gauge(f"{NS}_drift_detected", "1 if drift is detected on the rolling window")
DRIFT_CATEGORY_PSI = Gauge(f"{NS}_drift_category_psi", "PSI of predicted-category distribution")
DRIFT_LENGTH_PSI = Gauge(f"{NS}_drift_length_psi", "PSI of text-length distribution")
DRIFT_OOV = Gauge(f"{NS}_drift_oov_rate", "Mean out-of-vocabulary rate in the window")
DRIFT_OOV_INCREASE = Gauge(f"{NS}_drift_oov_increase", "OOV-rate increase over the training reference")
DRIFT_WINDOW = Gauge(f"{NS}_drift_window_size", "Requests currently in the drift window")


class PipelineCollector:
    """Reads pipeline artefacts at scrape time and exposes them as gauges."""

    def __init__(self, reports_dir: Path) -> None:
        self.reports_dir = reports_dir

    def collect(self):  # noqa: ANN201 - prometheus_client collector protocol
        duration = GaugeMetricFamily(f"{NS}_pipeline_stage_last_duration_seconds",
                                     "Duration of the latest run of each DVC stage", labels=["stage"])
        throughput = GaugeMetricFamily(f"{NS}_pipeline_stage_last_throughput_rows_per_second",
                                       "Rows/second of the latest run of each stage", labels=["stage"])
        status = GaugeMetricFamily(f"{NS}_pipeline_stage_last_success",
                                   "1 if the latest run of the stage succeeded", labels=["stage"])
        runs = GaugeMetricFamily(f"{NS}_pipeline_stage_runs", "Stage runs recorded in the run log",
                                 labels=["stage", "status"])
        last_ts = GaugeMetricFamily(f"{NS}_pipeline_last_run_timestamp_seconds",
                                    "Unix time of the latest stage run")
        latest: dict[str, dict] = {}
        counts: dict[tuple[str, str], int] = {}
        newest = 0.0
        log = self.reports_dir / "pipeline_runs.jsonl"
        if log.exists():
            for line in log.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                latest[r["stage"]] = r
                counts[(r["stage"], r["status"])] = counts.get((r["stage"], r["status"]), 0) + 1
                with suppress(TypeError, ValueError, KeyError):
                    newest = max(newest, datetime.fromisoformat(r["finished_at"]).timestamp())
        for stage, r in latest.items():
            duration.add_metric([stage], float(r.get("duration_seconds", 0)))
            throughput.add_metric([stage], float(r.get("throughput_rows_per_sec", 0)))
            status.add_metric([stage], 1.0 if r.get("status") == "success" else 0.0)
        for (stage, st), n in counts.items():
            runs.add_metric([stage, st], n)
        last_ts.add_metric([], newest)
        yield from (duration, throughput, status, runs, last_ts)

        offline = GaugeMetricFamily(f"{NS}_offline_metric", "Latest offline evaluation metric (test set)",
                                    labels=["metric"])
        metrics_file = self.reports_dir / "metrics.json"
        if metrics_file.exists():
            try:
                for k, v in json.loads(metrics_file.read_text()).items():
                    if isinstance(v, int | float):
                        offline.add_metric([k], float(v))
            except (json.JSONDecodeError, OSError):
                pass
        yield offline


_registered = False


def register_pipeline_collector(reports_dir: Path) -> None:
    """Register the collector once per process (idempotent for tests)."""
    global _registered
    if not _registered:
        REGISTRY.register(PipelineCollector(reports_dir))
        _registered = True
