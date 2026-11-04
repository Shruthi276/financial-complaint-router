"""Pipeline console data: DVC DAG, stage run history and latest reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


class PipelineService:
    """Reads ``dvc.yaml``, ``dvc.lock``-free run logs and JSON reports from the workspace."""

    REPORT_FILES = ("ingest", "preprocess", "data_validation", "split", "train_run", "metrics",
                    "per_class_metrics", "registration")

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def dag(self) -> dict[str, Any]:
        """Nodes = stages; edge A->B when an output of A is (a prefix of) a dependency of B."""
        path = self.workspace / "dvc.yaml"
        if not path.exists():
            return {"nodes": [], "edges": []}
        stages = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("stages", {})

        def paths(items: list | None) -> list[str]:
            out = []
            for item in items or []:
                out.append(next(iter(item)) if isinstance(item, dict) else str(item))
            return out

        produced: dict[str, list[str]] = {}
        nodes = []
        for name, spec in stages.items():
            outs = paths(spec.get("outs")) + paths(spec.get("metrics")) + paths(spec.get("plots"))
            produced[name] = outs
            nodes.append({"id": name, "description": spec.get("desc", ""), "cmd": spec.get("cmd", ""),
                          "deps": paths(spec.get("deps")), "outs": outs})
        edges = []
        for node in nodes:
            for dep in node["deps"]:
                for src, outs in produced.items():
                    if src != node["id"] and any(dep == o or dep.startswith(o.rstrip("/") + "/")
                                                 or o.startswith(dep.rstrip("/") + "/") for o in outs):
                        edge = {"source": src, "target": node["id"]}
                        if edge not in edges:
                            edges.append(edge)
        return {"nodes": nodes, "edges": edges}

    def runs(self, limit: int = 100) -> list[dict[str, Any]]:
        log = self.workspace / "reports" / "pipeline_runs.jsonl"
        if not log.exists():
            return []
        rows = []
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(rows[-limit:]))

    def summary(self) -> dict[str, Any]:
        runs = self.runs(limit=10000)
        latest: dict[str, dict] = {}
        for r in reversed(runs):  # oldest -> newest so the newest wins
            latest[r["stage"]] = r
        return {
            "total_runs": len(runs),
            "succeeded": sum(r["status"] == "success" for r in runs),
            "failed": sum(r["status"] == "failed" for r in runs),
            "latest_by_stage": latest,
        }

    def reports(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in self.REPORT_FILES:
            f = self.workspace / "reports" / f"{name}.json"
            if f.exists():
                try:
                    out[name] = json.loads(f.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    out[name] = {"error": "unreadable"}
        return out
