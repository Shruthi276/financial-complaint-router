"""Shared fixtures: a small synthetic complaint corpus and a fitted router."""

from __future__ import annotations

import random

import pandas as pd
import pytest

from complaint_router.model.router_model import ComplaintRouter, RouterConfig
from complaint_router.text_cleaning import normalize_text

TEMPLATES = {
    "credit_reporting": ["incorrect information on my credit report from the bureau",
                         "the credit bureau refuses to remove an inaccurate account from my report",
                         "my credit score dropped because of a wrong late payment on my report"],
    "debt_collection": ["a debt collector keeps calling me about a debt i do not owe",
                        "the collection agency threatened to sue me over an old debt",
                        "collector called my employer about the debt and harassed me"],
    "mortgage": ["my mortgage servicer misapplied my escrow payment",
                 "the lender started foreclosure while my loan modification was pending",
                 "mortgage payment increased because of escrow shortage on my home loan"],
    "credit_card": ["unauthorized charges on my credit card statement were not refunded",
                    "the card issuer charged an annual fee and late fee on my credit card",
                    "my credit card rewards points were removed without notice"],
    "bank_account": ["the bank charged overdraft fees on my checking account",
                     "my savings account was closed and the bank kept my deposit",
                     "a withdrawal from my checking account was never credited back"],
}


def make_corpus(n_per_class: int = 40, seed: int = 0) -> pd.DataFrame:
    """Synthetic but learnable corpus (template + random filler words)."""
    rng = random.Random(seed)
    filler = "please help me resolve this issue i called many times and nobody answered".split()
    rows = []
    for cat, templates in TEMPLATES.items():
        for i in range(n_per_class):
            text = f"{rng.choice(templates)} {' '.join(rng.sample(filler, 6))} case {i}"
            priority = int(any(w in text for w in ("unauthorized", "foreclosure", "sue", "harassed")))
            rows.append({"complaint_id": f"{cat}-{i}", "date_received": "2024-01-01",
                         "text": normalize_text(text), "category": cat, "priority": priority,
                         "issue": "synthetic", "company_response": "Closed with explanation"})
    df = pd.DataFrame(rows).sample(frac=1, random_state=seed).reset_index(drop=True)
    df["n_chars"] = df["text"].str.len()
    return df


@pytest.fixture(scope="session")
def corpus() -> pd.DataFrame:
    return make_corpus()


@pytest.fixture(scope="session")
def fitted_router(corpus: pd.DataFrame) -> ComplaintRouter:
    cfg = RouterConfig(model_type="logreg", min_df=1, max_features=2000, similar_index_size=100, max_iter=500)
    router = ComplaintRouter(cfg).fit(corpus["text"], corpus["category"], corpus["priority"], corpus)
    router.tune_priority_threshold(corpus["text"], corpus["priority"])
    return router
