#!/usr/bin/env bash
# Quick post-deployment check of every service. Exit code 1 if anything is down.
set -uo pipefail
fail=0
check() {
  local name=$1 url=$2
  if curl -fsS -m 5 -o /dev/null "$url"; then
    printf "  \033[32m✔\033[0m %-14s %s\n" "$name" "$url"
  else
    printf "  \033[31m✘\033[0m %-14s %s\n" "$name" "$url"; fail=1
  fi
}
echo "Service health:"
check frontend     http://localhost:8080/
check backend      http://localhost:8000/health
check mlflow       http://localhost:5000/health
check model-server http://localhost:5001/ping
check retrainer    http://localhost:8001/health
check prometheus   http://localhost:9090/-/ready
check alertmanager http://localhost:9093/-/ready
check grafana      http://localhost:3000/api/health

echo -e "\nSample prediction:"
curl -fsS -m 20 -X POST http://localhost:8000/api/v1/predict -H 'Content-Type: application/json' \
  -d '{"text":"A debt collector keeps calling me about a debt I already paid and threatened to sue me."}' \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print("  ->", d["team"], "| confidence", format(d["confidence"], ".2f"), "| priority", d["priority"])' \
  || { echo "  prediction failed (is a model trained? run: make train)"; fail=1; }
exit $fail
