"""TC-U01..U08: text normalisation and record cleaning."""

import pandas as pd

from complaint_router.text_cleaning import CLEAN_COLUMNS, clean_records, mask_pii, normalize_text


def test_redaction_tokens_removed():
    assert "xx" not in normalize_text("Called on XX/XX/XXXX about account XXXX")


def test_money_amount_tagged():
    assert "moneyamt" in normalize_text("They charged me {$450.00} twice")


def test_pii_is_masked():
    out = mask_pii("mail john.doe@example.com or call 555-123-4567, acct 12345678")
    assert "john" not in out and "555" not in out and "12345678" not in out
    assert "emailaddr" in out and "phonenum" in out and "acctnum" in out


def test_lowercase_and_whitespace():
    assert normalize_text("  Hello\n\nWORLD!!  ") == "hello world"


def test_non_string_input_returns_empty():
    assert normalize_text(None) == ""
    assert normalize_text(float("nan")) == ""


def test_truncation():
    assert len(normalize_text("word " * 5000, max_chars=100)) == 100


def test_clean_records_maps_labels_and_filters():
    raw = pd.DataFrame({
        "complaint_id": ["1", "2", "3", "4"],
        "date_received": ["2024-01-05T00:00:00", "2024-01-06", "2024-01-07", "2024-01-08"],
        "product": ["Mortgage", "Credit card", "Unknown product", "Debt collection"],
        "issue": ["Struggling to pay mortgage", "Fees or interest", "x", "Attempts to collect debt not owed"],
        "sub_issue": [None, None, None, None],
        "complaint_what_happened": ["My servicer refused my payment and started foreclosure on my house " * 2,
                                    "The card charged an annual fee that was never disclosed to me at all",
                                    "Some text long enough to pass the minimum character filter here",
                                    "short"],
        "company_response": ["Closed", None, None, None],
    })
    out = clean_records(raw, min_chars=50)
    assert list(out.columns) == CLEAN_COLUMNS
    assert out["complaint_id"].tolist() == ["1", "2"]          # unknown product + short text dropped
    assert out["category"].tolist() == ["mortgage", "credit_card"]
    assert out["priority"].tolist() == [1, 0]
    assert out["date_received"].iloc[0] == "2024-01-05"


def test_clean_records_empty_batch():
    assert list(clean_records(pd.DataFrame()).columns) == CLEAN_COLUMNS
