"""Turn a pytest JUnit XML file into the Markdown test report (docs/test_report.md).

Usage: python scripts/generate_test_report.py reports/tests/junit.xml docs/test_report.md
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


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
        f"| {totals['time']:.1f} s |",
        "", f"**Acceptance criterion AC-1 (all automated tests pass): {verdict}**", "",
        "## Test cases", "", "| Module | Test | Result | Time (s) | Detail |", "|---|---|---|---|---|",
    ]
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
