"""Stage 3 - validate: data-quality gate before any training happens.

Checks schema, nulls, label domain, minimum volume and per-class support, and
writes ``reports/data_validation.json``. Any failed check aborts the DVC
pipeline (non-zero exit), so a bad data drop can never produce a model.
"""

from __future__ import annotations

import sys

import pandas as pd

from complaint_router.categories import CATEGORY_KEYS
from complaint_router.config import load_params, project_path
from complaint_router.logging_utils import get_logger
from complaint_router.pipeline.run_log import stage_run, write_json
from complaint_router.text_cleaning import CLEAN_COLUMNS

logger = get_logger(__name__)
INPUT_PATH = project_path("data", "processed", "complaints_clean.parquet")


class DataValidationError(Exception):
    """Raised when the processed dataset fails a quality check."""


def run_checks(df: pd.DataFrame, cfg: dict) -> list[dict]:
    """Return a list of ``{"check", "passed", "detail"}`` results."""
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    missing = [c for c in CLEAN_COLUMNS if c not in df.columns]
    add("schema", not missing, f"missing columns: {missing}" if missing else "all columns present")
    add("min_rows", len(df) >= cfg["min_rows"], f"{len(df)} rows (min {cfg['min_rows']})")
    if missing:
        return checks
    null_frac = float(df[["text", "category", "priority"]].isna().mean().max()) if len(df) else 1.0
    add("nulls", null_frac <= cfg["max_null_fraction"], f"max null fraction {null_frac:.4f}")
    unknown = sorted(set(df["category"].dropna()) - set(CATEGORY_KEYS))
    add("label_domain", not unknown, f"unknown categories: {unknown}" if unknown else "all labels known")
    add("priority_binary", set(df["priority"].unique()) <= {0, 1}, "priority in {0,1}")
    counts = df["category"].value_counts()
    add("min_classes", counts.size >= cfg["min_classes"], f"{counts.size} classes (min {cfg['min_classes']})")
    small = counts[counts < cfg["min_rows_per_class"]].to_dict()
    # Under-represented classes are reported but not fatal: split.py drops them.
    add("class_support", True, f"classes below {cfg['min_rows_per_class']} rows (dropped later): {small}")
    add("empty_text", bool((df["n_chars"] > 0).all()), "no empty texts")
    return checks


def main() -> None:
    cfg = load_params()["validate"]
    with stage_run("validate") as run:
        df = pd.read_parquet(INPUT_PATH)
        run.rows_in = run.rows_out = len(df)
        checks = run_checks(df, cfg)
        passed = all(c["passed"] for c in checks)
        write_json(project_path("reports", "data_validation.json"), {"passed": passed, "checks": checks})
        for c in checks:
            logger.info("[%s] %-15s %s", "PASS" if c["passed"] else "FAIL", c["check"], c["detail"])
        if not passed:
            raise DataValidationError("Data validation failed: " +
                                      ", ".join(c["check"] for c in checks if not c["passed"]))


if __name__ == "__main__":
    try:
        main()
    except DataValidationError:
        sys.exit(1)
