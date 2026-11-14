"""Stage 1 - ingest: get raw CFPB complaints into data/raw/.

ingest.source in params.yaml:
  hf_mirror - download CFPB data from the HuggingFace mirror
  local     - use your own parquet/csv file
  sample    - use the small sample in data/sample (works offline)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import requests

from complaint_router.config import load_params, project_path
from complaint_router.logging_utils import get_logger
from complaint_router.pipeline.run_log import stage_run, write_json

logger = get_logger(__name__)

RAW_COLUMNS = ["complaint_id", "date_received", "product", "sub_product", "issue", "sub_issue",
               "complaint_what_happened", "company", "state", "tags", "company_response", "timely"]
# Column names of the official CFPB CSV export -> our snake_case names.
CSV_RENAMES = {
    "Complaint ID": "complaint_id", "Date received": "date_received", "Product": "product",
    "Sub-product": "sub_product", "Issue": "issue", "Sub-issue": "sub_issue",
    "Consumer complaint narrative": "complaint_what_happened", "Company": "company",
    "State": "state", "Tags": "tags", "Company response to consumer": "company_response",
    "Timely response?": "timely",
}
OUTPUT_PATH = project_path("data", "raw", "complaints.parquet")


def download(url: str, dest: Path, timeout: int) -> Path:
    """Stream ``url`` to ``dest`` (atomic rename). Re-uses an existing file."""
    if dest.exists() and dest.stat().st_size > 0:
        logger.info("Using cached download %s", dest)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    logger.info("Downloading %s", url)
    with requests.get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    tmp.replace(dest)
    return dest


def read_table(path: Path) -> pa.Table:
    """Read a parquet or CFPB-format csv file into an Arrow table with RAW_COLUMNS."""
    if path.suffix == ".csv":
        df = pd.read_csv(path, dtype=str).rename(columns=CSV_RENAMES)
        table = pa.Table.from_pandas(df, preserve_index=False)
    else:
        available = pq.read_schema(path).names
        table = pq.read_table(path, columns=[c for c in RAW_COLUMNS if c in available])
    missing = [c for c in ("complaint_what_happened", "product") if c not in table.column_names]
    if missing:
        raise ValueError(f"{path} is missing required columns {missing}")
    for col in RAW_COLUMNS:  # add optional columns so the schema is stable
        if col not in table.column_names:
            table = table.append_column(col, pa.array([None] * table.num_rows, type=pa.string()))
    return table.select(RAW_COLUMNS).cast(pa.schema([(c, pa.string()) for c in RAW_COLUMNS]))


def collect_sources(cfg: dict) -> list[Path]:
    """Resolve (and download if needed) the input files for the configured source."""
    source = cfg["source"]
    if source == "hf_mirror":
        cache = project_path(cfg["download_cache"])
        return [download(f"{cfg['hf_base_url']}/{cfg['hf_shard_template'].format(shard=s)}",
                         cache / cfg["hf_shard_template"].format(shard=s), cfg["timeout_seconds"])
                for s in cfg["shards"]]
    if source == "local":
        return [project_path(cfg["local_path"])]
    if source == "sample":
        return [project_path(cfg["sample_path"])]
    raise ValueError(f"Unknown ingest.source {source!r}")


def main() -> None:
    cfg = load_params()["ingest"]
    with stage_run("ingest") as run:
        sources = collect_sources(cfg)
        table = pa.concat_tables([read_table(p) for p in sources])
        # Keep only rows that have a narrative: the model cannot learn from empty text.
        has_text = pc.greater(pc.utf8_length(pc.fill_null(table["complaint_what_happened"], "")), 0)
        filtered = table.filter(has_text)
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(filtered, OUTPUT_PATH, compression="zstd")
        run.rows_in, run.rows_out = table.num_rows, filtered.num_rows
        run.extra = {"source": cfg["source"], "files": [p.name for p in sources]}
        write_json(project_path("reports", "ingest.json"), {
            "source": cfg["source"], "rows_total": table.num_rows,
            "rows_with_narrative": filtered.num_rows,
            "raw_size_mb": round(OUTPUT_PATH.stat().st_size / 1e6, 2),
        })


if __name__ == "__main__":
    main()
