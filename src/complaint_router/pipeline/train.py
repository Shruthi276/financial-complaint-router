"""Stage 5 - train: train the ComplaintRouter and log it to MLflow.

Besides sklearn autolog we log: params, data sizes, git commit and data md5
tags, validation metrics, top terms per class and the pyfunc model.
The run id is saved to reports/train_run.json for the next stages.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: autolog renders plots in worker threads
import mlflow  # noqa: E402
import mlflow.sklearn  # noqa: E402
import pandas as pd  # noqa: E402
from mlflow.models import ModelSignature  # noqa: E402
from mlflow.types.schema import ColSpec, Schema  # noqa: E402
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score  # noqa: E402

from complaint_router.config import load_params, project_path  # noqa: E402
from complaint_router.logging_utils import get_logger  # noqa: E402
from complaint_router.model.pyfunc_wrapper import ComplaintRouterPyfunc  # noqa: E402
from complaint_router.model.router_model import ComplaintRouter, RouterConfig  # noqa: E402
from complaint_router.pipeline.mlflow_utils import environment_tags, file_md5, setup_mlflow  # noqa: E402
from complaint_router.pipeline.run_log import git_commit, stage_run, write_json  # noqa: E402

logger = get_logger(__name__)
SPLIT_DIR = project_path("data", "splits")
PACKAGE_DIR = str(Path(__file__).resolve().parents[1])  # src/complaint_router, shipped with the model
MODEL_PATH = project_path("models", "router.joblib")
# Model input/output schema; top_k_similar is optional.
SIGNATURE = ModelSignature(
    inputs=Schema([ColSpec("string", "text"), ColSpec("long", "top_k_similar", required=False)]),
    outputs=Schema([ColSpec("string", "result")]),
)
EXAMPLE_TEXT = ("I noticed an unauthorized charge on my credit card statement and the bank "
                "refuses to refund it even though I reported it as fraud.")


def main() -> None:
    params = load_params()
    cfg = RouterConfig.from_params(params["train"], params["evaluate"])
    setup_mlflow(params["mlflow"]["experiment_name"])

    with stage_run("train") as run:
        train = pd.read_parquet(SPLIT_DIR / "train.parquet")
        val = pd.read_parquet(SPLIT_DIR / "val.parquet")
        run.rows_in = len(train)

        with mlflow.start_run(run_name=f"train-{cfg.model_type}") as mlrun:
            mlflow.set_tags({
                "git_commit": git_commit(), "pipeline_id": os.environ.get("PIPELINE_ID", "manual"),
                "data.train_md5": file_md5(SPLIT_DIR / "train.parquet"),
                "data.val_md5": file_md5(SPLIT_DIR / "val.parquet"),
                "trigger": os.environ.get("TRAIN_TRIGGER", "manual"),
                **environment_tags(),
            })
            mlflow.log_params({f"train.{k}": v for k, v in params["train"].items()})
            mlflow.log_params({"split.max_per_class": params["split"]["max_per_class"],
                               "preprocess.engine": params["preprocess"]["engine"],
                               "data.n_train": len(train), "data.n_val": len(val)})
            mlflow.log_dict(train["category"].value_counts().to_dict(), "data/class_balance_train.json")

            router = ComplaintRouter(cfg)
            t0 = time.perf_counter()
            X = router.fit_vectorizer(train["text"])
            mlflow.log_metric("vocabulary_size", len(router.vectorizer.vocabulary_))

            # autolog captures estimator params + training scores in nested runs
            mlflow.sklearn.autolog(log_models=False, log_datasets=False, silent=True)
            with mlflow.start_run(run_name="category-classifier", nested=True):
                router.fit_category(X, train["category"])
            with mlflow.start_run(run_name="priority-classifier", nested=True):
                router.fit_priority(X, train["priority"])
            mlflow.sklearn.autolog(disable=True)

            router.build_index(X, train["text"], train["category"], train["priority"], train)
            threshold = router.tune_priority_threshold(val["text"], val["priority"])
            train_seconds = time.perf_counter() - t0

            # ---- validation metrics
            proba = router.predict_proba(val["text"])
            pred = router.classes_[proba.argmax(axis=1)]
            prio_scores = router.priority_model.predict_proba(router.vectorizer.transform(val["text"]))[:, 1]
            prio_pred = (prio_scores >= threshold).astype(int)
            val_metrics = {
                "val_accuracy": accuracy_score(val["category"], pred),
                "val_macro_f1": f1_score(val["category"], pred, average="macro"),
                "val_priority_recall": recall_score(val["priority"], prio_pred, zero_division=0),
                "val_priority_precision": precision_score(val["priority"], prio_pred, zero_division=0),
                "priority_threshold": threshold, "train_seconds": train_seconds,
            }
            mlflow.log_metrics(val_metrics)
            mlflow.log_dict(router.top_terms_per_class(20), "explainability/top_terms_per_class.json")

            # ---- persist + log the servable model
            MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            router.save(str(MODEL_PATH))
            mlflow.log_metric("model_size_mb", MODEL_PATH.stat().st_size / 1e6)
            example = pd.DataFrame({"text": [EXAMPLE_TEXT], "top_k_similar": [3]})
            mlflow.pyfunc.log_model(
                artifact_path="model", python_model=ComplaintRouterPyfunc(),
                artifacts={"router": str(MODEL_PATH)},
                code_paths=[PACKAGE_DIR],
                signature=SIGNATURE, input_example=example,
                pip_requirements=str(project_path("requirements", "ml.lock.txt")),
            )
            run_id = mlrun.info.run_id

        run.rows_out = len(train)
        run.extra = {"mlflow_run_id": run_id, "val_macro_f1": round(val_metrics["val_macro_f1"], 4)}
        write_json(project_path("reports", "train_run.json"), {
            "mlflow_run_id": run_id, "model_type": cfg.model_type,
            **{k: round(float(v), 4) for k, v in val_metrics.items()},
        })
        logger.info("Training done: run %s, val macro-F1 %.4f", run_id, val_metrics["val_macro_f1"])


if __name__ == "__main__":
    main()
