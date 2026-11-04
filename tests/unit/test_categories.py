"""TC-U09..U13: routing taxonomy and priority rules."""

from complaint_router.categories import (
    CATEGORIES,
    CATEGORY_KEYS,
    PRODUCT_TO_CATEGORY,
    is_high_priority_issue,
    map_product,
    urgent_keywords_in,
)


def test_every_mapped_product_targets_a_known_category():
    assert set(PRODUCT_TO_CATEGORY.values()) <= set(CATEGORY_KEYS)


def test_nine_categories_with_teams():
    assert len(CATEGORIES) == 9
    assert all(c.team and c.label for c in CATEGORIES)


def test_map_product_handles_legacy_names_and_unknowns():
    assert map_product("Credit reporting") == "credit_reporting"
    assert map_product("Payday loan") == "payday_personal_loan"
    assert map_product("  Mortgage ") == "mortgage"
    assert map_product("Other financial service") is None
    assert map_product(None) is None


def test_priority_issue_rule():
    assert is_high_priority_issue("Fraud or scam", None)
    assert is_high_priority_issue("Loan modification,collection,foreclosure", "")
    assert is_high_priority_issue("Communication tactics", "Used obscene, profane, or other abusive language")
    assert not is_high_priority_issue("Incorrect information on your report", "Account status incorrect")


def test_urgent_keywords_detected_once_in_order():
    assert urgent_keywords_in("FRAUD! They committed fraud and threatened foreclosure") == [
        "fraud", "threaten", "foreclosure"]
    assert urgent_keywords_in("my statement was late") == []
