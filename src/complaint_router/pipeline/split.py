"""Stage 4 - split: cap each class at max_per_class (credit reporting is most of
the data) and make a stratified train/val/test split."""

from __future__ import annotations

import pandas as pd
from sklearn.model_selection import train_test_split

from complaint_router.config import load_params, project_path
from complaint_router.pipeline.run_log import stage_run, write_json

INPUT_PATH = project_path("data", "processed", "complaints_clean.parquet")
OUT_DIR = project_path("data", "splits")


def balanced_sample(df: pd.DataFrame, max_per_class: int, min_per_class: int, seed: int) -> pd.DataFrame:
    """Keep at most ``max_per_class`` rows per category; drop classes below ``min_per_class``."""
    counts = df["category"].value_counts()
    keep = counts[counts >= min_per_class].index
    df = df[df["category"].isin(keep)]
    parts = [g.sample(n=min(len(g), max_per_class), random_state=seed) for _, g in df.groupby("category")]
    return pd.concat(parts).reset_index(drop=True) if parts else df.iloc[0:0]


def split(df: pd.DataFrame, test_size: float, val_size: float, seed: int
          ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Stratified train/val/test split on the category label."""
    train_val, test = train_test_split(df, test_size=test_size, stratify=df["category"], random_state=seed)
    rel_val = val_size / (1 - test_size)
    train, val = train_test_split(train_val, test_size=rel_val, stratify=train_val["category"], random_state=seed)
    return train.reset_index(drop=True), val.reset_index(drop=True), test.reset_index(drop=True)


def main() -> None:
    params = load_params()
    cfg = params["split"]
    with stage_run("split") as run:
        df = pd.read_parquet(INPUT_PATH)
        sampled = balanced_sample(df, cfg["max_per_class"], params["validate"]["min_rows_per_class"], cfg["seed"])
        train, val, test = split(sampled, cfg["test_size"], cfg["val_size"], cfg["seed"])
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        for name, part in (("train", train), ("val", val), ("test", test)):
            part.to_parquet(OUT_DIR / f"{name}.parquet", index=False)
        run.rows_in, run.rows_out = len(df), len(sampled)
        write_json(project_path("reports", "split.json"), {
            "rows_available": len(df), "rows_sampled": len(sampled),
            "train": len(train), "val": len(val), "test": len(test),
            "class_counts_train": train["category"].value_counts().to_dict(),
            "priority_rate_train": round(float(train["priority"].mean()), 4),
        })


if __name__ == "__main__":
    main()
