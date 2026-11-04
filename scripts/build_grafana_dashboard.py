"""Generate monitoring/grafana/dashboards/complaint_router.json (dashboard-as-code).

Run: python scripts/build_grafana_dashboard.py
"""

from __future__ import annotations

import json
from pathlib import Path

DS = {"type": "prometheus", "uid": "prometheus"}
OUT = Path(__file__).resolve().parents[1] / "monitoring" / "grafana" / "dashboards" / "complaint_router.json"
_panels: list[dict] = []
_id = 0


def panel(kind: str, title: str, targets: list[tuple[str, str]], x: int, y: int, w: int, h: int,
          unit: str | None = None, description: str = "", **extra) -> None:
    global _id
    _id += 1
    p = {
        "id": _id, "type": kind, "title": title, "description": description, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [{"datasource": DS, "expr": e, "legendFormat": lg, "refId": chr(65 + i)}
                    for i, (e, lg) in enumerate(targets)],
        "fieldConfig": {"defaults": {}, "overrides": []}, "options": {},
    }
    if unit:
        p["fieldConfig"]["defaults"]["unit"] = unit
    for k, v in extra.items():
        if k == "thresholds":
            p["fieldConfig"]["defaults"]["thresholds"] = {"mode": "absolute", "steps": v}
        elif k == "fieldConfig":
            p["fieldConfig"]["defaults"].update(v["defaults"])
        elif k == "min_max":
            p["fieldConfig"]["defaults"]["min"], p["fieldConfig"]["defaults"]["max"] = v
        else:
            p[k] = v
    _panels.append(p)


def row(title: str, y: int) -> None:
    global _id
    _id += 1
    _panels.append({"id": _id, "type": "row", "title": title, "collapsed": False,
                    "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []})


GREEN_RED = [{"color": "green", "value": None}, {"color": "red", "value": 1}]
NS = "complaint_router"

row("Service health", 0)
panel("stat", "Model server", [(f"{NS}_model_server_up", "")], 0, 1, 4, 4,
      thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}],
      options={"colorMode": "background"},
      fieldConfig={"defaults": {"mappings": [{"type": "value", "options": {
          "0": {"text": "DOWN"}, "1": {"text": "UP"}}}]}, "overrides": []})
panel("stat", "Champion model version", [(f"{NS}_champion_model_version", "")], 4, 1, 4, 4)
panel("stat", "Requests / min", [(f"sum(rate({NS}_http_requests_total{{endpoint=~\"/api/v1/predict.*\"}}[1m]))*60", "")],
      8, 1, 4, 4, unit="short")
panel("stat", "p95 latency (predict)", [(
    f"histogram_quantile(0.95, sum(rate({NS}_http_request_duration_seconds_bucket{{endpoint=\"/api/v1/predict\"}}[5m])) by (le))",
    "")], 12, 1, 4, 4, unit="s",
    thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 0.5}, {"color": "red", "value": 1}])
panel("stat", "Error rate (5xx)", [(
    f"sum(rate({NS}_http_requests_total{{status=~\"5..\"}}[5m])) / clamp_min(sum(rate({NS}_http_requests_total[5m])), 0.001)",
    "")], 16, 1, 4, 4, unit="percentunit",
    thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 0.05}])
panel("stat", "Services up", [("sum(up)", "up"), ("count(up)", "total")], 20, 1, 4, 4)

row("Latency & throughput", 5)
panel("timeseries", "API latency percentiles", [
    (f"histogram_quantile(0.5, sum(rate({NS}_http_request_duration_seconds_bucket[5m])) by (le))", "p50"),
    (f"histogram_quantile(0.95, sum(rate({NS}_http_request_duration_seconds_bucket[5m])) by (le))", "p95"),
    (f"histogram_quantile(0.95, sum(rate({NS}_model_inference_duration_seconds_bucket[5m])) by (le))",
     "p95 model server"),
], 0, 6, 12, 8, unit="s")
panel("timeseries", "Requests by endpoint / status", [
    (f"sum(rate({NS}_http_requests_total[1m])) by (endpoint, status)", "{{endpoint}} {{status}}")],
    12, 6, 12, 8, unit="reqps")

row("Predictions", 14)
panel("piechart", "Predicted category distribution", [
    (f"sum(increase({NS}_predictions_total[$__range])) by (category)", "{{category}}")], 0, 15, 8, 9,
    options={"legend": {"displayMode": "table", "placement": "right", "values": ["value"]},
             "reduceOptions": {"calcs": ["lastNotNull"]}, "pieType": "donut"})
panel("timeseries", "High-priority rate", [
    (f"sum(rate({NS}_predictions_total{{priority=\"high\"}}[5m])) / clamp_min(sum(rate({NS}_predictions_total[5m])), 0.001)",
     "high priority share")], 8, 15, 8, 9, unit="percentunit", min_max=(0, 1))
panel("timeseries", "Confidence", [
    (f"sum(rate({NS}_prediction_confidence_sum[5m])) / clamp_min(sum(rate({NS}_prediction_confidence_count[5m])), 0.001)",
     "mean confidence"),
    (f"sum(rate({NS}_low_confidence_predictions_total[5m])) / clamp_min(sum(rate({NS}_predictions_total[5m])), 0.001)",
     "low-confidence share")], 16, 15, 8, 9, unit="percentunit", min_max=(0, 1))

row("Data drift (triggers automatic retraining)", 24)
panel("timeseries", "Drift signals", [
    (f"{NS}_drift_category_psi", "category PSI"), (f"{NS}_drift_length_psi", "length PSI"),
    (f"{NS}_drift_oov_increase", "OOV increase"), (f"{NS}_drift_score", "composite score")], 0, 25, 12, 8,
    thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 0.25}],
    fieldConfig={"defaults": {"custom": {"thresholdsStyle": {"mode": "line"}}}, "overrides": []})
panel("stat", "Drift detected", [(f"{NS}_drift_detected", "")], 12, 25, 4, 4, thresholds=GREEN_RED,
      options={"colorMode": "background"},
      fieldConfig={"defaults": {"mappings": [{"type": "value", "options": {
          "0": {"text": "STABLE"}, "1": {"text": "DRIFT"}}}]}, "overrides": []})
panel("stat", "Drift window", [(f"{NS}_drift_window_size", "")], 16, 25, 4, 4)
panel("stat", "Retraining running", [("retrainer_in_progress", "")], 20, 25, 4, 4,
      thresholds=[{"color": "text", "value": None}, {"color": "blue", "value": 1}])
panel("stat", "Retrains (success / failed)", [
    ("sum(retrainer_runs_total{status=\"success\"}) or vector(0)", "success"),
    ("sum(retrainer_runs_total{status=\"failed\"}) or vector(0)", "failed")], 12, 29, 6, 4)
panel("stat", "Model deployments", [("sum(model_server_restarts_total) or vector(0)", "")], 18, 29, 6, 4)

row("ML pipeline (DVC stages)", 33)
panel("bargauge", "Last stage duration", [(f"{NS}_pipeline_stage_last_duration_seconds", "{{stage}}")],
      0, 34, 8, 8, unit="s", options={"orientation": "horizontal", "displayMode": "gradient"})
panel("bargauge", "Last stage throughput", [(f"{NS}_pipeline_stage_last_throughput_rows_per_second", "{{stage}}")],
      8, 34, 8, 8, unit="short", options={"orientation": "horizontal", "displayMode": "gradient"})
panel("bargauge", "Offline test metrics (champion run)", [
    (f"{NS}_offline_metric{{metric=~\"test_(accuracy|macro_f1|priority_recall|priority_precision)\"}}",
     "{{metric}}")], 16, 34, 8, 8, unit="percentunit", min_max=(0, 1),
    options={"orientation": "horizontal", "displayMode": "lcd"})

row("Infrastructure (VM)", 42)
panel("timeseries", "CPU usage", [
    ("1 - avg(rate(node_cpu_seconds_total{mode=\"idle\"}[1m]))", "cpu")], 0, 43, 12, 7,
    unit="percentunit", min_max=(0, 1))
panel("timeseries", "Memory usage", [
    ("1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes", "memory")], 12, 43, 12, 7,
    unit="percentunit", min_max=(0, 1))

dashboard = {
    "uid": "complaint-router", "title": "Financial Complaint Router", "tags": ["aiops", "mlops"],
    "timezone": "browser", "schemaVersion": 39, "version": 1, "refresh": "10s",
    "time": {"from": "now-1h", "to": "now"}, "panels": _panels,
}

if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dashboard, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(_panels)} panels)")
