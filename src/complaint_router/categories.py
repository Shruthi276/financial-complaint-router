"""Routing categories, the CFPB product -> category mapping and the priority rules.

CFPB renamed its products a few times, so ~20 raw product names are merged
into 9 categories, each handled by one team.
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

# Training label for priority. CFPB has no urgency field, so a complaint is
# marked high priority when its issue/sub-issue contains one of these words.
HIGH_PRIORITY_ISSUE_PATTERNS: tuple[str, ...] = (
    "fraud", "scam", "identity theft", "unauthorized", "embezzlement", "stolen",
    "foreclosure", "repossess", "struggling to pay", "struggling to repay",
    "can't repay", "unable to pay", "threatened", "threat", "illegal action",
    "negative or legal action", "harass", "abusive", "lawsuit", "garnish",
)

# Words searched in the complaint text at prediction time and shown to the agent.
# Most are too common to decide on their own, so the model score decides...
URGENT_TEXT_KEYWORDS: tuple[str, ...] = (
    "fraud", "scam", "identity theft", "stolen", "unauthorized", "hacked",
    "foreclosure", "eviction", "evicted", "repossess", "garnish", "lawsuit", "sued",
    "threaten", "harass", "bankruptcy", "homeless", "elderly", "veteran",
    "servicemember", "disabled", "medical emergency",
)

# ...except these severe cases, which are always escalated.
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
