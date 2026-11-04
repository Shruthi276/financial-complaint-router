# Low-Level Design - Financial Complaint Router

Interactive OpenAPI docs: `http://<host>:8000/docs` (generated from the same pydantic models as below).

## 1. Modules

| Module | Key classes / functions |
|---|---|
| `src/complaint_router/categories.py` | `Category`, `CATEGORIES`, `map_product()`, `is_high_priority_issue()`, `urgent_keywords_in()`, `ESCALATION_KEYWORDS` |
| `src/complaint_router/text_cleaning.py` | `normalize_text()`, `mask_pii()`, `clean_records()` (Ray `map_batches` function) |
| `src/complaint_router/model/router_model.py` | `RouterConfig`, `ComplaintRouter.fit / fit_vectorizer / fit_category / fit_priority / build_index / tune_priority_threshold / predict / priority_decision / save / load` |
| `src/complaint_router/model/pyfunc_wrapper.py` | `ComplaintRouterPyfunc` (MLflow pyfunc) |
| `src/complaint_router/monitoring/drift.py` | `psi()`, `histogram()`, `distribution()`, `drift_report()` |
| `src/complaint_router/feedback.py` | `append_feedback()` (Fernet-encrypted), `read_feedback()`, `load_feedback_examples()` |
| `src/complaint_router/pipeline/*.py` | one module per DVC stage + `run_log.stage_run()` context manager |
| `backend/app/main.py` | `create_app()`, `AppState`, routes |
| `backend/app/model_client.py` | `ModelServerClient`, `ModelUnavailableError`, `ModelResponseError` |
| `backend/app/registry.py` | `RegistryClient` |
| `backend/app/drift_monitor.py` | `DriftMonitor` |
| `backend/app/pipeline_service.py` | `PipelineService` (DAG from `dvc.yaml`, run log, reports) |
| `services/model_server/supervisor.py` | alias-following deploy loop |
| `services/retrainer/app.py` | webhook + manual trigger, `launch()`, cool-down |

## 2. Backend REST API (base URL configurable; default `http://<host>:8000`)

All bodies are JSON (`Content-Type: application/json`). Errors use `{"detail": "<message>"}` (422 validation errors: `detail` is a list).

### 2.1 `POST /api/v1/predict` - route one complaint

Request:

| Field | Type | Constraints | Default |
|---|---|---|---|
| `text` | string | 20-10,000 chars after trimming; ≥ 10 letters | required |
| `top_k_similar` | integer | 0-10 | 3 |

Response `200`:

| Field | Type | Description |
|---|---|---|
| `prediction_id` | string (32 hex) | Use it when sending feedback |
| `category` | enum (9 keys, see §3) | Predicted routing category |
| `category_label` / `team` | string | Display name and owning team |
| `confidence` | float 0-1 | Top-class probability |
| `low_confidence` | bool | `confidence < 0.5`: the UI asks for manual review |
| `alternatives` | list of `{category, category_label, probability}` | Top 3 classes |
| `priority` | `"high"` \| `"normal"` | Final urgency flag (model OR severe-keyword rule) |
| `priority_score` | float 0-1 | Priority model probability |
| `priority_threshold` | float | Tuned decision threshold |
| `priority_reasons` | list of string | Human-readable reasons |
| `explanation` | list of `{term, weight}` | Terms that pushed towards the predicted class |
| `similar_complaints` | list of `{complaint_id, similarity, category, category_label, priority, issue, date_received, company_response, snippet}` | Nearest past complaints |
| `text_stats` | `{n_chars, n_tokens, oov_rate}` | Input statistics (also feed drift detection) |
| `model_version` | string \| null | Registry version that answered |
| `latency_ms` | float | Model call latency |

Errors: `422` invalid input · `503` model server unavailable / not trained yet · `502` invalid model response · `500` unexpected.

Example:
```bash
curl -X POST http://localhost:8000/api/v1/predict -H 'Content-Type: application/json' \
  -d '{"text":"My servicer started foreclosure while my loan modification was pending","top_k_similar":2}'
```

### 2.2 `POST /api/v1/predict/batch`
Request `{"texts": [string, ...]}` (1-50 items, same per-text rules). Response `{"results": [PredictResponse, ...]}` (similar complaints omitted). Errors as above, plus `422` for more than 50 items.

### 2.3 `POST /api/v1/feedback` - agent correction

| Field | Type | Constraints |
|---|---|---|
| `prediction_id` | string | required |
| `complaint_text` | string | 20-10,000 chars |
| `predicted_category`, `correct_category` | enum (9 keys) | required |
| `predicted_priority`, `correct_priority` | `"high"` \| `"normal"` \| null | optional |

Response `200 {"stored": true, "message": "..."}`. The record is Fernet-encrypted and appended to `data/feedback/feedback.enc.jsonl`, and the next `preprocess` run uses it. Errors: `422`, `503` (no encryption key configured), `500` (write error).

### 2.4 Read-only endpoints

| Method & path | Response |
|---|---|
| `GET /health` | `{status: ok\|degraded, model_server: up\|down, model_version, mlflow: up\|down, uptime_seconds}` |
| `GET /ready` | `200 {ready: true}` or `503` |
| `GET /metrics` | Prometheus text exposition |
| `GET /api/v1/categories` | `[{key, label, team, description}]` × 9 |
| `GET /api/v1/examples` | `[{title, text}]` demo complaints |
| `GET /api/v1/model` | `{model_name, champion: {version, run_id, created, metrics, params, git_commit}}` |
| `GET /api/v1/monitoring/drift` | `{status, window_size, min_samples, drift_detected, drift_score, category_psi, length_psi, oov_rate_live, oov_rate_reference, oov_increase}` |
| `GET /api/v1/pipeline/dag` | `{nodes: [{id, description, cmd, deps, outs}], edges: [{source, target}]}` |
| `GET /api/v1/pipeline/runs?limit=100` | `{summary: {total_runs, succeeded, failed, latest_by_stage}, runs: [StageRun]}` newest first |
| `GET /api/v1/pipeline/reports` | latest JSON reports (ingest, preprocess, data_validation, split, train_run, metrics, per_class_metrics, registration) |
| `GET /api/v1/pipeline/models` | `{versions: [{version, run_id, created, status, aliases, test_macro_f1, gate}], experiment_runs: [...]}` |
| `GET /api/v1/pipeline/retrain` | retrainer status `{running, current, cooldown_seconds, history}` |

`StageRun` = `{stage, run_id, pipeline_id, started_at, finished_at, status: success|failed, duration_seconds, rows_in, rows_out, throughput_rows_per_sec, git_commit, error, extra}`.

### 2.5 `POST /api/v1/pipeline/retrain` (admin)
Header `X-Admin-Token: <ADMIN_TOKEN>`. Body `{"reason": string ≤ 200}`. Response `{accepted, message, job?}`. Errors `401` (bad token), `503` (retrainer unreachable).

## 3. Category keys

`credit_reporting`, `debt_collection`, `mortgage`, `credit_card`, `bank_account`, `student_loan`, `vehicle_consumer_loan`, `payday_personal_loan`, `money_transfer`.

## 4. Internal interfaces

### 4.1 Model server (MLflow scoring protocol)
`POST http://model-server:5001/invocations`
```json
{"dataframe_records": [{"text": "...", "top_k_similar": 3}]}
```
Signature: inputs `text: string` (required), `top_k_similar: long` (optional). Output `result: string`.
Response: `{"predictions": [{"result": "<JSON-encoded decision>"}]}`. The decision has the fields of §2.1 except `prediction_id`, `model_version` and `latency_ms`, which the backend adds. Health: `GET /ping`.

### 4.2 Retrainer
| Endpoint | Purpose |
|---|---|
| `POST /webhook/alertmanager` | Alertmanager v4 payload. Starts a run only for *firing* alerts labelled `action="retrain"`, respecting the cool-down. |
| `POST /retrain` (X-Admin-Token) | Manual run, ignores the cool-down. |
| `GET /status`, `GET /health`, `GET /metrics` | Status, history, Prometheus metrics |

### 4.3 Prometheus metrics (prefix `complaint_router_`)
`http_requests_total{method,endpoint,status}`, `http_request_duration_seconds{endpoint}`, `model_inference_duration_seconds`, `model_errors_total{type}`, `model_server_up`, `champion_model_version`, `predictions_total{category,priority}`, `prediction_confidence`, `priority_score`, `low_confidence_predictions_total`, `input_text_chars`, `feedback_total{outcome}`, `drift_score`, `drift_detected`, `drift_category_psi`, `drift_length_psi`, `drift_oov_rate`, `drift_oov_increase`, `drift_window_size`, `pipeline_stage_last_duration_seconds{stage}`, `pipeline_stage_last_throughput_rows_per_second{stage}`, `pipeline_stage_last_success{stage}`, `pipeline_stage_runs{stage,status}`, `pipeline_last_run_timestamp_seconds`, `offline_metric{metric}`.
Retrainer: `retrainer_runs_total{trigger,status}`, `retrainer_in_progress`, `retrainer_last_duration_seconds`, `retrainer_last_success_timestamp_seconds`, `retrainer_skipped_total{reason}`. Model server: `model_server_process_up`, `model_server_served_version`, `model_server_restarts_total{reason}`.

## 5. Pipeline stages (`dvc.yaml`)

| Stage | Inputs | Outputs | Fails when |
|---|---|---|---|
| ci_tests | `src/`, `tests/unit` | `reports/ci/unit_tests.xml` | any unit test fails |
| ingest | `params.ingest` | `data/raw/complaints.parquet`, `reports/ingest.json` | download / schema error |
| preprocess | raw parquet, `data/feedback`, cleaning code | `data/processed/complaints_clean.parquet`, `reports/preprocess.json` | Ray error |
| validate | processed parquet | `reports/data_validation.json` | schema, nulls, unknown label, volume, class-count check fails |
| split | processed parquet | `data/splits/{train,val,test}.parquet`, `reports/split.json` | - |
| train | splits, unit-test report | `models/router.joblib`, `reports/train_run.json`, MLflow run | MLflow unreachable |
| evaluate | model, test split | `reports/metrics.json`, `per_class_metrics.json`, `reference_stats.json`, confusion matrix (csv/png) | - |
| register | metrics, run id | `reports/registration.json`, registry version + aliases | MLflow unreachable (a failed *gate* is not an error: the champion is kept) |

## 6. Configuration (environment variables)

| Service | Variable | Default |
|---|---|---|
| backend | `MODEL_SERVER_URL`, `MLFLOW_TRACKING_URI`, `RETRAINER_URL` | compose service URLs |
| backend | `ADMIN_TOKEN`, `FEEDBACK_ENCRYPTION_KEY` | generated by `make env` |
| backend | `CORS_ORIGINS` | `*` |
| backend | `DRIFT_WINDOW`, `DRIFT_MIN_SAMPLES`, `DRIFT_PSI_THRESHOLD`, `DRIFT_OOV_THRESHOLD` | 200, 50, 0.25, 0.15 |
| frontend | `API_BASE_URL`, `GRAFANA_URL`, `MLFLOW_URL`, `PROMETHEUS_URL`, `ALERTMANAGER_URL` | empty = same host, default ports |
| model-server | `MODEL_NAME`, `MODEL_ALIAS`, `POLL_SECONDS`, `SERVE_WORKERS` | complaint-router, champion, 20, 2 |
| retrainer | `RETRAIN_COOLDOWN_SECONDS`, `RETRAIN_COMMAND` | 1800, `dvc repro --force` |
