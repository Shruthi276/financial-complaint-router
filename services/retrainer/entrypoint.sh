#!/usr/bin/env bash
# Retrainer container start-up: make git/dvc usable on the bind-mounted repo,
# then serve the webhook API.
set -euo pipefail
git config --global --add safe.directory /workspace || true
git config --global user.name  "${GIT_AUTHOR_NAME:-retrainer}"  || true
git config --global user.email "${GIT_AUTHOR_EMAIL:-retrainer@localhost}" || true
cd /workspace
mkdir -p reports logs data/feedback
exec uvicorn app:app --app-dir /opt/services/retrainer --host 0.0.0.0 --port 8001
