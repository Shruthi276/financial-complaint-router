"""FastAPI backend: the REST API used by the web UI (docs at /docs)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager, suppress
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app import metrics as m
from app.drift_monitor import DriftMonitor
from app.examples import EXAMPLES
from app.model_client import ModelResponseError, ModelServerClient, ModelUnavailableError
from app.pipeline_service import PipelineService
from app.registry import RegistryClient
from app.schemas import (
    BatchPredictRequest,
    BatchPredictResponse,
    CategoryInfo,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    PredictRequest,
    PredictResponse,
    RetrainRequest,
)
from app.settings import Settings
from complaint_router.categories import CATEGORIES
from complaint_router.feedback import append_feedback

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
logger = logging.getLogger("backend")


class AppState:
    """Process-wide singletons (created in the lifespan handler)."""

    def __init__(self, settings: Settings, model_client: ModelServerClient | None = None,
                 registry: RegistryClient | None = None) -> None:
        self.settings = settings
        self.model = model_client or ModelServerClient(settings.model_server_url, settings.model_timeout_seconds)
        self.registry = registry or RegistryClient(settings.mlflow_tracking_uri, settings.model_name,
                                                   settings.experiment_name)
        self.drift = DriftMonitor(settings.drift_window, settings.drift_min_samples,
                                  settings.drift_psi_threshold, settings.drift_oov_threshold)
        self.pipeline = PipelineService(settings.workspace_dir)
        self.started = time.time()


def _fingerprint(text: str) -> str:
    """Short hash of the text, so complaint text is never written to logs."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _local_reference(settings: Settings) -> dict | None:
    path = settings.reports_dir / "reference_stats.json"
    try:
        return json.loads(path.read_text()) if path.exists() else None
    except (OSError, json.JSONDecodeError):
        return None


async def sync_champion(state: AppState) -> None:
    """Pick up a newly promoted champion: update version gauge + drift reference."""
    champion, changed = await asyncio.to_thread(state.registry.refresh_champion)
    if champion and changed:
        ref = await asyncio.to_thread(state.registry.reference_stats, champion["run_id"])
        state.drift.set_reference(ref or _local_reference(state.settings))
    elif state.drift.reference is None:
        state.drift.set_reference(_local_reference(state.settings))


async def _registry_watcher(state: AppState) -> None:
    while True:
        with suppress(Exception):
            await sync_champion(state)
            await state.model.ping()
            state.drift.report()
        await asyncio.sleep(state.settings.registry_poll_seconds)


def create_app(settings: Settings | None = None, model_client: ModelServerClient | None = None,
               registry: RegistryClient | None = None, start_background: bool = True) -> FastAPI:
    """Application factory (dependencies are injectable for tests)."""
    settings = settings or Settings()
    m.register_pipeline_collector(settings.reports_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        app.state.ctx = AppState(settings, model_client, registry)
        task = asyncio.create_task(_registry_watcher(app.state.ctx)) if start_background else None
        logger.info("Backend started (model server %s)", settings.model_server_url)
        yield
        if task:
            task.cancel()
        await app.state.ctx.model.close()

    app = FastAPI(title="Financial Complaint Router API", version="1.0.0", lifespan=lifespan,
                  description="Routes customer complaints to the right team, flags urgent ones and "
                              "retrieves similar past complaints. See docs/LLD.md for the full contract.")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type", "X-Admin-Token"])

    @app.middleware("http")
    async def prometheus_middleware(request: Request, call_next):  # noqa: ANN001, ANN202
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled error on %s", request.url.path)
            response = JSONResponse({"detail": "Internal server error"}, status_code=500)
        route = request.scope.get("route")
        endpoint = getattr(route, "path", "unmatched")
        if endpoint != "/metrics":
            m.HTTP_LATENCY.labels(endpoint=endpoint).observe(time.perf_counter() - start)
            m.HTTP_REQUESTS.labels(request.method, endpoint, str(response.status_code)).inc()
        return response

    def ctx(request: Request) -> AppState:
        return request.app.state.ctx

    def require_admin(x_admin_token: str = Header("", alias="X-Admin-Token"),
                      state: AppState = Depends(ctx)) -> None:
        if not state.settings.admin_token or x_admin_token != state.settings.admin_token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing admin token")

    async def _predict(state: AppState, texts: list[str], top_k: int) -> list[PredictResponse]:
        for t in texts:
            if not (settings.min_text_chars <= len(t) <= settings.max_text_chars):
                raise HTTPException(422, f"Each complaint must be {settings.min_text_chars}-"
                                         f"{settings.max_text_chars} characters long")
        start = time.perf_counter()
        try:
            decisions = await state.model.predict(texts, top_k)
        except ModelUnavailableError as exc:
            logger.warning("Model unavailable: %s", exc)
            raise HTTPException(503, "The routing model is not available right now. If this is a fresh "
                                     "install, train a model first (make train). Otherwise retry shortly.") from exc
        except ModelResponseError as exc:
            logger.error("Model error: %s", exc)
            raise HTTPException(502, "The routing model returned an invalid answer") from exc
        latency_ms = (time.perf_counter() - start) * 1000 / max(len(texts), 1)
        version = state.registry.champion["version"] if state.registry.champion else None

        out = []
        for text, d in zip(texts, decisions, strict=False):
            pid = uuid.uuid4().hex
            m.PREDICTIONS.labels(d["category"], d["priority"]).inc()
            m.CONFIDENCE.observe(d["confidence"])
            m.PRIORITY_SCORE.observe(d["priority_score"])
            m.TEXT_LENGTH.observe(len(text))
            if d["low_confidence"]:
                m.LOW_CONFIDENCE.inc()
            state.drift.observe(d["category"], d["text_stats"]["n_chars"], d["text_stats"]["oov_rate"])
            logger.info("prediction id=%s text=%s len=%d -> %s (%.2f) priority=%s", pid, _fingerprint(text),
                        len(text), d["category"], d["confidence"], d["priority"])
            out.append(PredictResponse(prediction_id=pid, model_version=version,
                                       latency_ms=round(latency_ms, 2), **d))
        return out

    # ------------------------------------------------------------------ routes
    @app.get("/health", response_model=HealthResponse, tags=["ops"])
    async def health(state: AppState = Depends(ctx)) -> HealthResponse:
        model_up, mlflow_up = await asyncio.gather(state.model.ping(),
                                                   asyncio.to_thread(state.registry.available))
        version = state.registry.champion["version"] if state.registry.champion else None
        return HealthResponse(status="ok" if model_up else "degraded", model_server="up" if model_up else "down",
                              model_version=version, mlflow="up" if mlflow_up else "down",
                              uptime_seconds=round(time.time() - state.started, 1))

    @app.get("/ready", tags=["ops"])
    async def ready(state: AppState = Depends(ctx)) -> dict:
        if not await state.model.ping():
            raise HTTPException(503, "model server not ready")
        return {"ready": True}

    @app.get("/metrics", tags=["ops"], include_in_schema=False)
    async def metrics(state: AppState = Depends(ctx)) -> Response:
        state.drift.report()
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/api/v1/predict", response_model=PredictResponse, tags=["routing"])
    async def predict(req: PredictRequest, state: AppState = Depends(ctx)) -> PredictResponse:
        return (await _predict(state, [req.text], req.top_k_similar))[0]

    @app.post("/api/v1/predict/batch", response_model=BatchPredictResponse, tags=["routing"])
    async def predict_batch(req: BatchPredictRequest, state: AppState = Depends(ctx)) -> BatchPredictResponse:
        if len(req.texts) > settings.max_batch:
            raise HTTPException(422, f"At most {settings.max_batch} complaints per batch")
        texts = [t.strip() for t in req.texts]
        return BatchPredictResponse(results=await _predict(state, texts, 0))

    @app.post("/api/v1/feedback", response_model=FeedbackResponse, tags=["routing"])
    async def feedback(req: FeedbackRequest, state: AppState = Depends(ctx)) -> FeedbackResponse:
        outcome = "correct" if req.correct_category == req.predicted_category else "corrected"
        try:
            await asyncio.to_thread(append_feedback, state.settings.feedback_dir, req.model_dump())
        except RuntimeError as exc:
            logger.error("Feedback not stored: %s", exc)
            raise HTTPException(503, "Feedback storage is not configured") from exc
        except OSError as exc:
            logger.error("Feedback write failed: %s", exc)
            raise HTTPException(500, "Could not save feedback") from exc
        m.FEEDBACK.labels(outcome=outcome).inc()
        return FeedbackResponse(stored=True, message="Thank you - your feedback will be used in the next retraining.")

    @app.get("/api/v1/categories", response_model=list[CategoryInfo], tags=["routing"])
    async def categories() -> list[CategoryInfo]:
        return [CategoryInfo(key=c.key, label=c.label, team=c.team, description=c.description) for c in CATEGORIES]

    @app.get("/api/v1/examples", tags=["routing"])
    async def examples() -> list[dict]:
        return EXAMPLES

    @app.get("/api/v1/model", tags=["model"])
    async def model_info(state: AppState = Depends(ctx)) -> dict:
        await sync_champion(state)
        return {"model_name": settings.model_name, "champion": state.registry.champion}

    @app.get("/api/v1/monitoring/drift", tags=["monitoring"])
    async def drift(state: AppState = Depends(ctx)) -> dict:
        return state.drift.report()

    @app.get("/api/v1/pipeline/dag", tags=["pipeline"])
    async def pipeline_dag(state: AppState = Depends(ctx)) -> dict:
        return state.pipeline.dag()

    @app.get("/api/v1/pipeline/runs", tags=["pipeline"])
    async def pipeline_runs(limit: int = 100, state: AppState = Depends(ctx)) -> dict:
        limit = max(1, min(limit, 1000))
        return {"summary": state.pipeline.summary(), "runs": state.pipeline.runs(limit)}

    @app.get("/api/v1/pipeline/reports", tags=["pipeline"])
    async def pipeline_reports(state: AppState = Depends(ctx)) -> dict:
        return state.pipeline.reports()

    @app.get("/api/v1/pipeline/models", tags=["pipeline"])
    async def pipeline_models(state: AppState = Depends(ctx)) -> dict:
        versions, runs = await asyncio.gather(asyncio.to_thread(state.registry.list_versions),
                                              asyncio.to_thread(state.registry.recent_runs, 20))
        return {"versions": versions, "experiment_runs": runs}

    async def _retrainer(method: str, path: str, **kw: Any) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.request(method, f"{settings.retrainer_url}{path}", **kw)
        except httpx.HTTPError as exc:
            raise HTTPException(503, "Retraining service is not reachable") from exc
        if resp.status_code >= 400:
            raise HTTPException(resp.status_code, resp.json().get("detail", "retrainer error"))
        return resp.json()

    @app.get("/api/v1/pipeline/retrain", tags=["pipeline"])
    async def retrain_status() -> dict:
        return await _retrainer("GET", "/status")

    @app.post("/api/v1/pipeline/retrain", tags=["pipeline"], dependencies=[Depends(require_admin)])
    async def retrain(req: RetrainRequest) -> dict:
        return await _retrainer("POST", "/retrain", json={"reason": req.reason, "trigger": "manual"},
                                headers={"X-Admin-Token": settings.admin_token})

    return app


app = create_app()
