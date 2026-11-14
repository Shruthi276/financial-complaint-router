"""Text cleaning functions, used in training (Ray/pandas) and at prediction time."""

from __future__ import annotations

import re

import pandas as pd

from complaint_router.categories import is_high_priority_issue, map_product

# CFPB already hides personal data as "XXXX"; we remove those and mask other PII.
_REDACTION_RE = re.compile(r"\bX{2,}(?:[/\-]X{2,})*\b", re.I)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
_LONG_NUMBER_RE = re.compile(r"\b\d{6,}\b")  # account / card / SSN-like numbers
_MONEY_RE = re.compile(r"\{\$[\d,]+(?:\.\d+)?\}")  # CFPB wraps amounts as {$450.00}
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_NON_TEXT_RE = re.compile(r"[^a-z0-9$%'\s]")
_WS_RE = re.compile(r"\s+")

# Columns produced by `clean_records`, in order.
CLEAN_COLUMNS = ["complaint_id", "date_received", "text", "category", "priority",
                 "issue", "company_response", "n_chars"]


def mask_pii(text: str) -> str:
    """Replace e-mails, phone numbers, long digit runs and URLs with placeholders."""
    text = _EMAIL_RE.sub(" emailaddr ", text)
    text = _URL_RE.sub(" urladdr ", text)
    text = _PHONE_RE.sub(" phonenum ", text)
    return _LONG_NUMBER_RE.sub(" acctnum ", text)


def normalize_text(text: str | None, max_chars: int = 6000) -> str:
    """Clean a complaint: remove XXXX tokens, mask PII, lower-case, remove
    punctuation and extra spaces. Same function for training and prediction."""
    if not isinstance(text, str) or not text:
        return ""
    text = _MONEY_RE.sub(" moneyamt ", text)
    text = _REDACTION_RE.sub(" ", text)
    text = mask_pii(text)
    text = text.lower()
    text = _NON_TEXT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text[:max_chars]


def clean_records(batch: pd.DataFrame, min_chars: int = 50, max_chars: int = 6000) -> pd.DataFrame:
    """Turn a batch of raw CFPB rows into training rows (used by Ray map_batches).
    Drops rows with no text, an unknown product, or too little text."""
    if batch.empty:
        return pd.DataFrame(columns=CLEAN_COLUMNS)

    def col(name: str) -> pd.Series:
        return batch[name] if name in batch.columns else pd.Series([None] * len(batch), index=batch.index)

    out = pd.DataFrame({
        "complaint_id": col("complaint_id").astype(str),
        "date_received": col("date_received").astype(str).str[:10],
        "text": col("complaint_what_happened").map(lambda t: normalize_text(t, max_chars)),
        "category": col("product").map(map_product),
        "priority": [int(is_high_priority_issue(i, s)) for i, s in zip(col("issue"), col("sub_issue"), strict=False)],
        "issue": col("issue").fillna("").astype(str),
        "company_response": col("company_response").fillna("").astype(str),
    })
    out["n_chars"] = out["text"].str.len()
    out = out[out["category"].notna() & (out["n_chars"] >= min_chars)]
    return out[CLEAN_COLUMNS].reset_index(drop=True)
