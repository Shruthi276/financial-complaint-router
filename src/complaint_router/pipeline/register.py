"""Stage 7 - register: model registry, acceptance gate and safe promotion.

Every trained model becomes a new version of ``complaint-router`` in the MLflow
Model Registry and receives the ``@challenger`` alias. It is promoted to
``@champion`` (the alias the model server follows) only if:

1. it clears the absolute acceptance bars in ``params.register``; and
2. its test macro-F1 is not worse than the current champion by more than
   ``max_regression``.

Otherwise the current champion keeps serving - an automatic guard against bad
retrains. ``scripts/rollback.py`` can move ``@champion`` back manually.
"""

from __future__ import annotations

import json

import mlflow
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from complaint_router.config import load_params, project_path
from complaint_router.logging_utils import get_logger
from complaint_router.pipeline.mlflow_utils import setup_mlflow
from complaint_router.pipeline.run_log import stage_run, write_json

logger = get_logger(__name__)
REPORTS = project_path("reports")


def champion_macro_f1(client: MlflowClient, name: str) -> tuple[str | None, float | None]:
    """Return (version, test_macro_f1) of the current champion, if any."""
    try:
        mv = client.get_model_version_by_alias(name, "champion")
    except MlflowException:
        return None, None
    metric = client.get_run(mv.run_id).data.metrics.get("test_macro_f1")
    return str(mv.version), metric


def decide(metrics: dict, champion_f1: float | None, cfg: dict) -> tuple[bool, list[str]]:
    """Pure promotion rule (unit tested). Returns (promote?, reasons)."""
    reasons = []
    ok = True
    if metrics["test_macro_f1"] < cfg["min_macro_f1"]:
        ok = False
        reasons.append(f"macro-F1 {metrics['test_macro_f1']:.4f} < required {cfg['min_macro_f1']}")
    if metrics["test_priority_recall"] < cfg["min_priority_recall"]:
        ok = False
        reasons.append(f"priority recall {metrics['test_priority_recall']:.4f} < required "
                       f"{cfg['min_priority_recall']}")
    flag_rate = metrics.get("test_priority_flag_rate", 0.0)
    if flag_rate > cfg.get("max_priority_flag_rate", 1.0):
        ok = False
        reasons.append(f"flags {flag_rate:.0%} of complaints urgent (max {cfg['max_priority_flag_rate']:.0%})")
    if champion_f1 is not None and metrics["test_macro_f1"] < champion_f1 - cfg["max_regression"]:
        ok = False
        reasons.append(f"macro-F1 {metrics['test_macro_f1']:.4f} regresses vs champion {champion_f1:.4f}")
    if ok:
        reasons.append("passed acceptance gate" + ("" if champion_f1 is None else
                                                   f" (champion macro-F1 {champion_f1:.4f})"))
    return ok, reasons


def main() -> None:
    params = load_params()
    cfg = params["register"]
    setup_mlflow(params["mlflow"]["experiment_name"])
    client = MlflowClient()
    name = cfg["model_name"]

    with stage_run("register") as run:
        run_id = json.loads((REPORTS / "train_run.json").read_text())["mlflow_run_id"]
        metrics = json.loads((REPORTS / "metrics.json").read_text())
        prev_version, prev_f1 = champion_macro_f1(client, name)
        promote, reasons = decide(metrics, prev_f1, cfg)

        mv = mlflow.register_model(f"runs:/{run_id}/model", name)
        version = str(mv.version)
        client.set_registered_model_alias(name, "challenger", version)
        client.set_model_version_tag(name, version, "test_macro_f1", str(metrics["test_macro_f1"]))
        client.set_model_version_tag(name, version, "gate", "passed" if promote else "rejected")
        if promote:
            client.set_registered_model_alias(name, "champion", version)
            logger.info("Promoted %s v%s to @champion", name, version)
        else:
            logger.warning("Kept champion v%s; candidate v%s rejected: %s", prev_version, version, reasons)

        run.rows_in = run.rows_out = 1
        run.extra = {"version": version, "promoted": promote}
        write_json(REPORTS / "registration.json", {
            "model_name": name, "candidate_version": version, "mlflow_run_id": run_id,
            "promoted": promote, "previous_champion": prev_version, "previous_champion_macro_f1": prev_f1,
            "candidate_macro_f1": metrics["test_macro_f1"], "reasons": reasons,
        })


if __name__ == "__main__":
    main()
