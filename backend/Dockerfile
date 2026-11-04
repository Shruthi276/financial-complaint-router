# FastAPI backend. Build context = repository root (needs src/complaint_router
# for the shared category / drift / feedback helpers - no ML libraries).
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/opt/app/src:/opt/app/backend HOME=/tmp
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements/backend.txt /tmp/requirements-backend.txt
RUN pip install -r /tmp/requirements-backend.txt
WORKDIR /opt/app
COPY src/complaint_router ./src/complaint_router
COPY backend/app ./backend/app
RUN useradd --create-home --uid 10001 api
USER api
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fs http://localhost:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
