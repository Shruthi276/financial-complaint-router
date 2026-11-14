# One image file for the 3 ML services (they share the same Python packages):
#   mlflow       - tracking server + model registry
#   model-server - mlflow models serve (follows @champion)
#   retrainer    - runs the DVC pipeline (make train, drift webhook)
FROM python:3.11-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    HOME=/tmp USER=aiops
RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl \
 && rm -rf /var/lib/apt/lists/*
# Exact package versions (made with `make lock`) so builds are repeatable.
COPY requirements/ml.lock.txt /tmp/requirements-ml.lock.txt
# Cache pip downloads between builds.
RUN --mount=type=cache,target=/root/.cache/pip PIP_NO_CACHE_DIR=0 pip install --retries 10 --timeout 120 -r /tmp/requirements-ml.lock.txt

FROM base AS mlflow
EXPOSE 5000
CMD ["sh", "-c", "mkdir -p /mlflow/artifacts /mlflow/prometheus && exec mlflow server --host 0.0.0.0 --port 5000 --backend-store-uri sqlite:////mlflow/mlflow.db --serve-artifacts --artifacts-destination /mlflow/artifacts --expose-prometheus /mlflow/prometheus --workers 2"]

FROM base AS model-server
COPY services/model_server/supervisor.py /opt/services/model_server/supervisor.py
EXPOSE 5001 9101
CMD ["python", "/opt/services/model_server/supervisor.py"]

FROM base AS retrainer
ENV PYTHONPATH=/workspace/src
COPY services/retrainer /opt/services/retrainer
WORKDIR /workspace
EXPOSE 8001
CMD ["bash", "/opt/services/retrainer/entrypoint.sh"]
