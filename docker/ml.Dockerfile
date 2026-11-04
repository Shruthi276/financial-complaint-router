# Multi-stage image for every "ML side" service. One dependency layer is
# shared, so the large wheels (Ray, MLflow, scikit-learn) download once.
#   target mlflow       -> tracking server + model registry
#   target model-server -> mlflow models serve, supervised (follows @champion)
#   target retrainer    -> DVC pipeline runner + drift webhook (also `make train`)
FROM python:3.11-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    HOME=/tmp USER=aiops
RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl \
 && rm -rf /var/lib/apt/lists/*
COPY requirements/ml.txt /tmp/requirements-ml.txt
RUN pip install -r /tmp/requirements-ml.txt

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
