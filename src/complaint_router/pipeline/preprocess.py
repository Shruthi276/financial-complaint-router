"""Stage 2 - preprocess: distributed cleaning with Ray Data.

raw parquet --(Ray read_parquet)--> blocks --(map_batches: clean_records)-->
--> pandas --(dedupe)--> data/processed/complaints_clean.parquet

``clean_records`` (see text_cleaning.py) normalises text, masks PII, maps the
CFPB product to a routing category and derives the weak priority label. Ray
parallelises it across ``preprocess.num_cpus`` workers; the same function runs
in plain pandas when ``preprocess.engine = pandas`` (tiny machines / tests).

Agent feedback collected through the web app (``data/feedback``) is decrypted
and appended as extra labelled examples, closing the human-in-the-loop cycle.
"""

from __future__ import annotations

import os
import time
from functools import partial

import pandas as pd

from complaint_router.config import load_params, project_path
from complaint_router.feedback import load_feedback_examples
from complaint_router.logging_utils import get_logger
from complaint_router.pipeline.run_log import stage_run, write_json
from complaint_router.text_cleaning import CLEAN_COLUMNS, clean_records

logger = get_logger(__name__)
RAW_PATH = project_path("data", "raw", "complaints.parquet")
OUTPUT_PATH = project_path("data", "processed", "complaints_clean.parquet")


def run_ray(cfg: dict) -> pd.DataFrame:
    """Clean the raw parquet with Ray Data and return the result as pandas."""
    import ray  # imported lazily: Ray is heavy and not needed for the pandas engine

    ray.init(num_cpus=int(cfg["num_cpus"]), include_dashboard=False, ignore_reinit_error=True,
             log_to_driver=False, object_store_memory=int(os.environ.get("RAY_OBJECT_STORE_BYTES", 512 * 1024**2)))
    try:
        ds = ray.data.read_parquet(str(RAW_PATH))
        cleaned = ds.map_batches(
            partial(clean_records, min_chars=cfg["min_chars"], max_chars=cfg["max_chars"]),
            batch_format="pandas", batch_size=int(cfg["batch_size"]),
        )
        return cleaned.to_pandas()
    finally:
        ray.shutdown()


def run_pandas(cfg: dict) -> pd.DataFrame:
    """Single-process fallback using the very same cleaning function."""
    raw = pd.read_parquet(RAW_PATH)
    size = int(cfg["batch_size"])
    parts = [clean_records(raw.iloc[i:i + size], cfg["min_chars"], cfg["max_chars"])
             for i in range(0, len(raw), size)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=CLEAN_COLUMNS)


def main() -> None:
    cfg = load_params()["preprocess"]
    with stage_run("preprocess") as run:
        rows_in = len(pd.read_parquet(RAW_PATH, columns=["complaint_id"]))
        t0 = time.perf_counter()
        df = run_ray(cfg) if cfg["engine"] == "ray" else run_pandas(cfg)
        transform_seconds = time.perf_counter() - t0

        before = len(df)
        df = df.drop_duplicates(subset="text").drop_duplicates(subset="complaint_id")
        deduped = len(df)
        feedback = load_feedback_examples(project_path("data", "feedback"))
        if not feedback.empty:
            logger.info("Adding %d agent-feedback examples", len(feedback))
            df = pd.concat([df, feedback[CLEAN_COLUMNS]], ignore_index=True)

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(OUTPUT_PATH, index=False)
        run.rows_in, run.rows_out = rows_in, len(df)
        stats = {
            "engine": cfg["engine"], "num_cpus": cfg["num_cpus"],
            "rows_in": rows_in, "rows_after_cleaning": before, "duplicates_removed": before - deduped,
            "feedback_rows": len(feedback), "rows_out": len(df),
            "transform_seconds": round(transform_seconds, 2),
            "throughput_rows_per_sec": round(rows_in / transform_seconds, 1) if transform_seconds else None,
            "category_counts": df["category"].value_counts().to_dict(),
            "priority_rate": round(float(df["priority"].mean()), 4) if len(df) else 0.0,
            "mean_chars": round(float(df["n_chars"].mean()), 1) if len(df) else 0.0,
        }
        run.extra = {"engine": cfg["engine"], "transform_seconds": stats["transform_seconds"]}
        write_json(project_path("reports", "preprocess.json"), stats)


if __name__ == "__main__":
    main()
