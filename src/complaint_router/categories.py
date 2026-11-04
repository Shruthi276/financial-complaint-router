"""Domain knowledge: routing categories, the CFPB product mapping and priority rules.

CFPB renamed its product taxonomy several times (2011, 2017, 2022), so the raw
``product`` column contains ~20 overlapping labels. We consolidate them into nine
routing categories, each owned by one operations team.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    """A routing destination shown to agents."""

    key: str
    label: str
    team: str
    description: str


CATEGORIES: tuple[Category, ...] = (
    Category("credit_reporting", "Credit Reporting", "Credit Bureau Disputes Team",
             "Errors on credit reports, credit scores, investigations of disputes."),
    Category("debt_collection", "Debt Collection", "Collections Compliance Team",
             "Collectors, debts not owed, collection tactics and notices."),
    Category("mortgage", "Mortgage", "Mortgage Servicing Team",
             "Home loans, escrow, modifications, foreclosure, closing."),
    Category("credit_card", "Credit / Prepaid Card", "Card Services Team",
             "Credit and prepaid cards: billing disputes, fees, rewards, card access."),
    Category("bank_account", "Bank Account", "Deposit Accounts Team",
             "Checking and savings accounts, deposits, withdrawals, overdrafts."),
    Category("student_loan", "Student Loan", "Student Lending Team",
             "Federal and private student loans, servicing, repayment plans."),
    Category("vehicle_consumer_loan", "Vehicle / Consumer Loan", "Auto & Installment Lending Team",
             "Auto loans and leases, other installment consumer loans."),
    Category("payday_personal_loan", "Payday / Personal Loan", "Short-term Lending Team",
             "Payday, title, personal and cash-advance loans."),
    Category("money_transfer", "Money Transfer / Crypto", "Payments & Transfers Team",
             "Wire transfers, P2P apps, mobile wallets, virtual currency."),
)

CATEGORY_BY_KEY: dict[str, Category] = {c.key: c for c in CATEGORIES}
CATEGORY_KEYS: tuple[str, ...] = tuple(c.key for c in CATEGORIES)

# Raw CFPB "product" value -> routing category key. Unlisted products are dropped.
PRODUCT_TO_CATEGORY: dict[str, str] = {
    "Credit reporting, credit repair services, or other personal consumer reports": "credit_reporting",
    "Credit reporting or other personal consumer reports": "credit_reporting",
    "Credit reporting": "credit_reporting",
    "Debt collection": "debt_collection",
    "Mortgage": "mortgage",
    "Credit card or prepaid card": "credit_card",
    "Credit card": "credit_card",
    "Prepaid card": "credit_card",
    "Checking or savings account": "bank_account",
    "Bank account or service": "bank_account",
    "Student loan": "student_loan",
    "Vehicle loan or lease": "vehicle_consumer_loan",
    "Consumer Loan": "vehicle_consumer_loan",
    "Payday loan, title loan, or personal loan": "payday_personal_loan",
    "Payday loan, title loan, personal loan, or advance loan": "payday_personal_loan",
    "Payday loan": "payday_personal_loan",
    "Money transfer, virtual currency, or money service": "money_transfer",
    "Money transfers": "money_transfer",
    "Virtual currency": "money_transfer",
}

# Weak-supervision rule for the priority label used in TRAINING.
# CFPB has no "urgency" field, so we label a complaint high priority when the
# consumer-selected issue/sub-issue describes fraud, loss of a home/vehicle,
# inability to pay, or abusive/illegal collection conduct. These are the issue
# types where regulators expect expedited handling.
HIGH_PRIORITY_ISSUE_PATTERNS: tuple[str, ...] = (
    "fraud", "scam", "identity theft", "unauthorized", "embezzlement", "stolen",
    "foreclosure", "repossess", "struggling to pay", "struggling to repay",
    "can't repay", "unable to pay", "threatened", "threat", "illegal action",
    "negative or legal action", "harass", "abusive", "lawsuit", "garnish",
)

# Urgency SIGNALS checked in the complaint text at inference time and shown to
# the agent. Most are too common to decide alone (e.g. "fraud" appears in ~15%
# of credit-report disputes), so the model score decides...
URGENT_TEXT_KEYWORDS: tuple[str, ...] = (
    "fraud", "scam", "identity theft", "stolen", "unauthorized", "hacked",
    "foreclosure", "eviction", "evicted", "repossess", "garnish", "lawsuit", "sued",
    "threaten", "harass", "bankruptcy", "homeless", "elderly", "veteran",
    "servicemember", "disabled", "medical emergency",
)

# ...except for these severe, high-precision situations (imminent loss of home,
# vehicle, wages or shelter), which are ALWAYS escalated. Precision measured on
# the CFPB test split: foreclosure 0.58, repossess 0.57, sued 0.48, garnish 0.44.
ESCALATION_KEYWORDS: frozenset[str] = frozenset({
    "foreclosure", "eviction", "evicted", "repossess", "garnish", "sued", "homeless", "medical emergency",
})

_URGENT_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in URGENT_TEXT_KEYWORDS) + r")", re.I)


def map_product(product: str | None) -> str | None:
    """Map a raw CFPB product name to a routing category key (``None`` if unmapped)."""
    if not product:
        return None
    return PRODUCT_TO_CATEGORY.get(product.strip())


def is_high_priority_issue(issue: str | None, sub_issue: str | None) -> bool:
    """Weak label: does the issue/sub-issue indicate a complaint needing fast handling?"""
    haystack = f"{issue or ''} {sub_issue or ''}".lower()
    return any(pattern in haystack for pattern in HIGH_PRIORITY_ISSUE_PATTERNS)


def urgent_keywords_in(text: str) -> list[str]:
    """Return the distinct urgent keywords found in ``text`` (lower-case, in order)."""
    seen: list[str] = []
    for match in _URGENT_RE.finditer(text or ""):
        word = match.group(1).lower()
        if word not in seen:
            seen.append(word)
    return seen
