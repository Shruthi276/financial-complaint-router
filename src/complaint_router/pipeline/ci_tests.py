"""Stage 0 - ci_tests: run the unit tests. If any test fails, the pipeline stops
before training, so a broken code change can never produce a model."""

from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET

from complaint_router.config import project_path
from complaint_router.pipeline.run_log import stage_run

REPORT = project_path("reports", "ci", "unit_tests.xml")


def main() -> None:
    with stage_run("ci_tests") as run:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/unit", "-q", f"--junitxml={REPORT}"],
            cwd=project_path(),
        )
        # number of tests, shown in the pipeline console
        suite = ET.parse(REPORT).getroot().find("testsuite")
        run.rows_in = run.rows_out = int(suite.get("tests", 0))
        if result.returncode != 0:
            raise RuntimeError(f"{suite.get('failures')} unit test(s) failed")


if __name__ == "__main__":
    main()
