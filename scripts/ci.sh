#!/usr/bin/env bash
# Local continuous integration (cloud CI services are not allowed in this project).
#   bash scripts/ci.sh          full: lint, tests, test report, dvc status, docker build
#   bash scripts/ci.sh --quick  pre-push: lint + unit tests + dvc status
# The model-side CI is the DVC DAG itself: `dvc repro` re-runs ci_tests and every
# stage whose inputs changed, and the register stage gates promotion.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[[ -x $PY ]] || PY=python3
QUICK=${1:-}
step() { echo -e "\n\033[1;36m[ci] $*\033[0m"; }

step "Lint (ruff, PEP8 + import order + bugbear)"
$PY -m ruff check src backend services tests scripts

if [[ $QUICK == "--quick" ]]; then
  step "Unit tests"
  $PY -m pytest tests/unit -q
else
  step "Unit + integration tests"
  mkdir -p reports/tests
  $PY -m pytest tests -q --junitxml=reports/tests/junit.xml
  step "Test report -> docs/test_report.md"
  $PY scripts/generate_test_report.py reports/tests/junit.xml docs/test_report.md
fi

step "DVC pipeline status (stages that would re-run)"
if command -v .venv/bin/dvc >/dev/null 2>&1 && [[ -d .dvc ]]; then
  .venv/bin/dvc status || true
  .venv/bin/dvc dag
fi

if [[ $QUICK != "--quick" ]] && command -v docker >/dev/null 2>&1; then
  step "Docker images build"
  docker compose build
fi
echo -e "\n\033[1;32m[ci] all checks passed\033[0m"
