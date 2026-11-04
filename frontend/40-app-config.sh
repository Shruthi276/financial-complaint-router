#!/bin/sh
# Writes the runtime configuration of the UI from environment variables, so the
# same image works on any host. Empty values -> the UI derives URLs from the
# hostname the page was opened with (e.g. http://<vm-ip>:8000 for the API).
set -eu
cat > /usr/share/nginx/html/config.js <<CFG
window.APP_CONFIG = {
  API_BASE_URL: "${API_BASE_URL:-}",
  GRAFANA_URL: "${GRAFANA_URL:-}",
  MLFLOW_URL: "${MLFLOW_URL:-}",
  PROMETHEUS_URL: "${PROMETHEUS_URL:-}",
  ALERTMANAGER_URL: "${ALERTMANAGER_URL:-}"
};
CFG
echo "UI config written (API_BASE_URL='${API_BASE_URL:-<auto>}')"
