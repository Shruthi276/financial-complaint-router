"""Stage 6 - evaluate: test metrics, confusion matrix and the reference
statistics used for drift detection. Results go to reports/ and MLflow."""

from __future__ import annotations

import json
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import mlflow  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from complaint_router.categories import urgent_keywords_in  # noqa: E402
from complaint_router.config import load_params, project_path  # noqa: E402
from complaint_router.logging_utils import get_logger  # noqa: E402
from complaint_router.model.router_model import ComplaintRouter  # noqa: E402
from complaint_router.monitoring.drift import histogram  # noqa: E402
from complaint_router.pipeline.mlflow_utils import setup_mlflow  # noqa: E402
from complaint_router.pipeline.run_log import stage_run, write_json  # noqa: E402

logger = get_logger(__name__)
REPORTS = project_path("reports")


def plot_confusion(cm: np.ndarray, labels: list[str], path) -> None:
    """Row-normalised confusion-matrix heat map."""
    norm = cm / np.clip(cm.sum(axis=1, keepdims=True), 1, None)
    fig, ax = plt.subplots(figsize=(9, 8))
    im = ax.imshow(norm, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, f"{norm[i, j]:.2f}", ha="center", va="center",
                    color="white" if norm[i, j] > 0.5 else "black", fontsize=8)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.set_title("Confusion matrix (row-normalised, test set)")
    fig.colorbar(im)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main() -> None:
    params = load_params()
    setup_mlflow(params["mlflow"]["experiment_name"])
    run_id = json.loads((REPORTS / "train_run.json").read_text())["mlflow_run_id"]

    with stage_run("evaluate") as run:
        test = pd.read_parquet(project_path("data", "splits", "test.parquet"))
        router = ComplaintRouter.load(str(project_path("models", "router.joblib")))
        run.rows_in = run.rows_out = len(test)

        t0 = time.perf_counter()
        proba = router.predict_proba(test["text"])
        batch_seconds = time.perf_counter() - t0
        pred = router.classes_[proba.argmax(axis=1)]
        confidence = proba.max(axis=1)
        X = router.vectorizer.transform(test["text"])
        prio_scores = router.priority_model.predict_proba(X)[:, 1]
        model_only = (prio_scores >= router.priority_threshold).astype(int)
        # The served decision = model OR urgent-keyword rule; evaluate exactly that.
        prio_pred = np.array([int(router.priority_decision(s, urgent_keywords_in(t)))
                              for s, t in zip(prio_scores, test["text"], strict=True)])

        # single-request latency of the full decision (incl. explanation + similar cases)
        sample = test["text"].head(50).tolist()
        t1 = time.perf_counter()
        for text in sample:
            router.predict([text])
        single_latency_ms = (time.perf_counter() - t1) / max(len(sample), 1) * 1000

        low_conf = params["evaluate"]["low_confidence_threshold"]
        metrics = {
            "test_accuracy": accuracy_score(test["category"], pred),
            "test_macro_f1": f1_score(test["category"], pred, average="macro"),
            "test_weighted_f1": f1_score(test["category"], pred, average="weighted"),
            "test_priority_recall": recall_score(test["priority"], prio_pred, zero_division=0),
            "test_priority_precision": precision_score(test["priority"], prio_pred, zero_division=0),
            "test_priority_f1": f1_score(test["priority"], prio_pred, zero_division=0),
            "test_priority_flag_rate": float(prio_pred.mean()),
            "test_priority_recall_model_only": recall_score(test["priority"], model_only, zero_division=0),
            "test_priority_precision_model_only": precision_score(test["priority"], model_only, zero_division=0),
            "test_priority_roc_auc": roc_auc_score(test["priority"], prio_scores)
            if test["priority"].nunique() > 1 else float("nan"),
            "test_low_confidence_rate": float((confidence < low_conf).mean()),
            "test_accuracy_when_confident": float((pred == test["category"])[confidence >= low_conf].mean()),
            "batch_throughput_per_sec": len(test) / batch_seconds if batch_seconds else 0.0,
            "single_prediction_latency_ms": single_latency_ms,
        }
        metrics = {k: round(float(v), 4) for k, v in metrics.items()}

        labels = [str(c) for c in router.classes_]
        cm = confusion_matrix(test["category"], pred, labels=labels)
        report = classification_report(test["category"], pred, labels=labels, output_dict=True, zero_division=0)
        per_class = {c: {k: round(v, 4) for k, v in report[c].items()} for c in labels}

        lengths = test["text"].str.len().tolist()
        oov = [router.oov_rate(t) for t in test["text"]]
        reference = {
            "classes": labels,
            "category_distribution": [float((pred == c).mean()) for c in labels],
            "length_histogram": histogram(lengths),
            "oov_rate_mean": float(np.mean(oov)), "oov_rate_std": float(np.std(oov)),
            "confidence_mean": float(confidence.mean()),
            "priority_rate": float(prio_pred.mean()),
            "mlflow_run_id": run_id,
        }

        write_json(REPORTS / "metrics.json", metrics)
        write_json(REPORTS / "per_class_metrics.json", per_class)
        write_json(REPORTS / "reference_stats.json", reference)
        pd.DataFrame([{"actual": a, "predicted": p} for a, p in zip(test["category"], pred, strict=False)]
                     ).to_csv(REPORTS / "confusion_matrix.csv", index=False)
        plot_confusion(cm, labels, REPORTS / "confusion_matrix.png")

        with mlflow.start_run(run_id=run_id):
            mlflow.log_metrics(metrics)
            for c, m in per_class.items():
                mlflow.log_metric(f"test_f1_{c}", m["f1-score"])
            for name in ("metrics.json", "per_class_metrics.json", "reference_stats.json",
                         "confusion_matrix.png"):
                mlflow.log_artifact(str(REPORTS / name), artifact_path="evaluation")
        run.extra = {"test_macro_f1": metrics["test_macro_f1"], "mlflow_run_id": run_id}
        logger.info("Test metrics: %s", metrics)


if __name__ == "__main__":
    main()
