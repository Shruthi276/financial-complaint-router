"""Turn a pytest JUnit XML file into the Markdown test report (docs/test_report.md).

Usage: python scripts/generate_test_report.py reports/tests/junit.xml docs/test_report.md
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


def acceptance_rows(rows: list[tuple], tests_verdict: str) -> list[str]:
    """One table row per acceptance criterion in docs/test_plan.md."""
    metrics_file = Path("reports/metrics.json")
    m = json.loads(metrics_file.read_text()) if metrics_file.exists() else {}

    def tests_pass(*names: str) -> str:
        found = [r for r in rows if r[1].startswith(names)]
        return "MET" if found and all(r[2] == "PASS" for r in found) else "NOT MET"

    def check(ok: bool) -> str:
        return "MET" if ok else "NOT MET"

    f1 = m.get("test_macro_f1", 0)
    recall, flag_rate = m.get("test_priority_recall", 0), m.get("test_priority_flag_rate", 1)
    latency = m.get("single_prediction_latency_ms", 99999)
    table = [
        ("AC-1", "All automated tests pass", f"{len(rows)} tests (list below)", tests_verdict),
        ("AC-2", "Test macro-F1 >= 0.70", f"macro-F1 = {f1:.3f} (reports/metrics.json)", check(f1 >= 0.70)),
        ("AC-3", "Urgent recall >= 0.65 and flag rate <= 35 %",
         f"recall = {recall:.3f}, flag rate = {flag_rate:.1%}", check(recall >= 0.65 and flag_rate <= 0.35)),
        ("AC-4", "A worse retrained model is not deployed", "TC-I04",
         tests_pass("test_second_worse_candidate_is_not_promoted")),
        ("AC-5", "Prediction latency < 1 s", f"{latency:.0f} ms per prediction (evaluate stage)",
         check(latency < 1000)),
        ("AC-6", "Bad input gives 422, model down gives a clear 503", "TC-I06, TC-I07",
         tests_pass("test_predict_rejects_invalid_input", "test_predict_returns_503_when_model_unavailable")),
        ("AC-7", "Complaint text is stored only encrypted", "TC-U35, TC-I10",
         tests_pass("test_feedback_is_encrypted_and_reloadable", "test_feedback_stored_encrypted")),
        ("AC-8", "Drift triggers retraining automatically", "manual scenario M-6 (`make drift`)", "Manual"),
        ("AC-9", "A non-technical user can route a complaint", "manual scenario M-1", "Manual"),
    ]
    return [f"| {i} | {c} | {e} | **{r}** |" for i, c, e, r in table]


def main(junit: str, out: str) -> int:
    root = ET.parse(junit).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    rows, totals = [], {"tests": 0, "passed": 0, "failed": 0, "skipped": 0, "time": 0.0}
    for suite in suites:
        for case in suite.iter("testcase"):
            status = "PASS"
            detail = ""
            for tag, label in (("failure", "FAIL"), ("error", "ERROR"), ("skipped", "SKIP")):
                node = case.find(tag)
                if node is not None:
                    message = node.get("message") or ""
                    status, detail = label, (message.splitlines()[0][:120] if message else "")
            module = case.get("classname", "").replace("tests.", "")
            rows.append((module, case.get("name", ""), status, float(case.get("time", 0)), detail))
            totals["tests"] += 1
            totals["time"] += float(case.get("time", 0))
            key = {"PASS": "passed", "SKIP": "skipped"}.get(status, "failed")
            totals[key] += 1

    verdict = "MET" if totals["failed"] == 0 and totals["tests"] > 0 else "NOT MET"
    lines = [
        "# Test Report - Financial Complaint Router", "",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M} from `{junit}` (see docs/test_plan.md for the plan "
        "and acceptance criteria).", "",
        "## Summary", "",
        "| Total | Passed | Failed | Skipped | Duration |", "|---|---|---|---|---|",
        f"| {totals['tests']} | {totals['passed']} | {totals['failed']} | {totals['skipped']} "
        f"| {totals['time']:.1f} s |", "",
        "## Acceptance criteria", "", "| ID | Criterion | Evidence | Result |", "|---|---|---|---|",
    ]
    lines += acceptance_rows(rows, verdict)
    lines += ["", "## Test cases", "", "| Module | Test | Result | Time (s) | Detail |", "|---|---|---|---|---|"]
    lines += [f"| {m} | `{n}` | {s} | {t:.2f} | {d.replace('|', '/')} |" for m, n, s, t, d in rows]
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{out}: {totals['passed']}/{totals['tests']} passed ({verdict})")
    return 0 if verdict == "MET" else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
