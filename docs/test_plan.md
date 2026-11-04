# Test Plan - Financial Complaint Router

## 1. Scope and objectives

Verify that the system (a) routes and prioritises complaints correctly and safely, (b) honours the API contract in [LLD.md](LLD.md), (c) runs the ML pipeline reproducibly with working quality gates, and (d) works as a deployed stack (UI ↔ API ↔ model server ↔ monitoring).

Out of scope: load testing beyond a single VM, and cross-browser testing other than current Chrome/Firefox.

## 2. Test levels and how to run them

| Level | Location | What it covers | Command | Runs in |
|---|---|---|---|---|
| Unit | `tests/unit` | Pure functions and classes: cleaning, taxonomy, drift maths, router model, pipeline logic, promotion gate, encryption | `make test-unit` | DVC stage `ci_tests` (gates training), pre-push hook, `make ci` |
| Integration | `tests/integration` | Real pipeline stages on the bundled CFPB sample (subprocesses + MLflow file store); pyfunc model loading; backend API with injected fakes; backend registry client against a real registry | `make test-integration` | `make ci` |
| End-to-end | `tests/e2e` (marker `e2e`) | Running docker stack: UI served, health, routing quality on known cases, urgent escalation, latency, all Prometheus targets up | `make up && make train && make test-e2e` | manual, before a release |
| Manual UI | checklist §5 | Usability, error states, responsiveness | browser | before a demo |
| Style | ruff (PEP8, isort, naming, bugbear, pyupgrade) | Coding standard | `make lint` | pre-push, `make ci` |

The report is produced by `make report`: it runs `pytest --junitxml` and then `scripts/generate_test_report.py` writes [test_report.md](test_report.md) with totals and per-case results.

## 3. Acceptance criteria

| ID | Criterion | Verified by |
|---|---|---|
| AC-1 | 100 % of automated unit + integration tests pass | test report |
| AC-2 | Test macro-F1 ≥ 0.70 on the held-out CFPB test split | `register` gate, `reports/metrics.json` |
| AC-3 | Urgent-complaint recall ≥ 0.65 and urgent flag rate ≤ 35 % | `register` gate |
| AC-4 | A retrained model that is worse than the champion is **not** deployed | TC-I04 |
| AC-5 | Single prediction p95 latency < 1 s on the VM | TC-E05, Grafana p95 panel, alert `HighInferenceLatency` |
| AC-6 | Invalid input never produces a 5xx; the model being down yields a clear 503 message | TC-I06, TC-I07 |
| AC-7 | Complaint text is never stored unencrypted or logged | TC-U35, TC-I10, code review of `main.py` logging |
| AC-8 | Sustained input drift triggers retraining without human action | manual scenario M-6 |
| AC-9 | A non-technical user can route a complaint without reading the manual | manual scenario M-1 |

## 4. Automated test cases

### Unit (tests/unit) - 42 cases incl. parametrisations

| ID | Test | Expectation |
|---|---|---|
| TC-U01 | `test_redaction_tokens_removed` | CFPB `XX/XX/XXXX` tokens removed |
| TC-U02 | `test_money_amount_tagged` | `{$450.00}` → `moneyamt` |
| TC-U03 | `test_pii_is_masked` | e-mail, phone and account numbers masked |
| TC-U04 | `test_lowercase_and_whitespace` | normalisation |
| TC-U05 | `test_non_string_input_returns_empty` | None/NaN safe |
| TC-U06 | `test_truncation` | max length enforced |
| TC-U07 | `test_clean_records_maps_labels_and_filters` | product→category, weak priority label, filters |
| TC-U08 | `test_clean_records_empty_batch` | empty Ray batch handled |
| TC-U09 | `test_every_mapped_product_targets_a_known_category` | taxonomy consistency |
| TC-U10 | `test_nine_categories_with_teams` | 9 categories with teams |
| TC-U11 | `test_map_product_handles_legacy_names_and_unknowns` | legacy names / unknown → None |
| TC-U12 | `test_priority_issue_rule` | weak-label rule |
| TC-U13 | `test_urgent_keywords_detected_once_in_order` | keyword extraction |
| TC-U14 | `test_psi_zero_for_identical_distributions` | PSI = 0 |
| TC-U15 | `test_psi_grows_with_shift` | PSI monotone |
| TC-U16 | `test_histogram_and_distribution_normalised` | distributions sum to 1 |
| TC-U17 | `test_no_drift_on_reference_like_traffic` | no false alarm |
| TC-U18 | `test_drift_detected_on_new_vocabulary_and_skewed_categories` | drift detected, score in [0.5, 1] |
| TC-U19 | `test_predicts_expected_categories` | correct routing |
| TC-U20 | `test_output_contract` | all response fields, ranges, ordering |
| TC-U21 | `test_explanation_terms_relate_to_text` | explanation terms come from the text |
| TC-U22 | `test_severe_keywords_always_escalate` | foreclosure → high, fraud shown as signal |
| TC-U23 | `test_priority_decision_rule` | rule truth table |
| TC-U24 | `test_priority_threshold_tuned_in_range` | threshold sanity |
| TC-U25 | `test_oov_rate` | OOV edge cases |
| TC-U26 | `test_save_load_roundtrip` | identical predictions after reload |
| TC-U27 | `test_alternative_model_types[sgd, cnb]` | all model types train and predict |
| TC-U28 | `test_invalid_usage` | bad model type / unfitted model raise |
| TC-U29 | `test_validation_passes_on_good_data` | quality gate passes |
| TC-U30 | `test_validation_fails_on_unknown_label_and_missing_column` | quality gate fails |
| TC-U31 | `test_balanced_sample_caps_and_drops` | class cap, tiny classes dropped |
| TC-U32 | `test_split_is_stratified_and_disjoint` | no leakage, all classes in test |
| TC-U33 | `test_promotion_gate[6 cases]` | gate accepts/rejects correctly (F1, recall, regression, flag rate) |
| TC-U34 | `test_stage_run_logs_success_and_failure` | run log records status/error |
| TC-U35 | `test_feedback_is_encrypted_and_reloadable` | ciphertext at rest, decryptable for training |
| TC-U36 | `test_feedback_refused_without_key` | never stores plaintext |

### Integration (tests/integration) - 22 cases

| ID | Test | Expectation |
|---|---|---|
| TC-I01 | `test_full_pipeline_on_sample` | ingest→register succeed on real CFPB sample; metrics, validation, reference stats, registry v1 promoted |
| TC-I02 | `test_run_log_records_every_stage` | every stage logged with throughput |
| TC-I03 | `test_logged_pyfunc_model_serves_predictions` | MLflow pyfunc honours `top_k_similar` (regression for signature bug) |
| TC-I04 | `test_second_worse_candidate_is_not_promoted` | crippled retrain v2 rejected, v1 stays champion |
| TC-I05 | `test_backend_registry_client_reads_real_registry` | versions as strings, nested runs hidden (regression) |
| TC-I06 | `test_predict_rejects_invalid_input[5 cases]` | 422 for short / non-text / missing / too long / bad top_k |
| TC-I07 | `test_predict_returns_503_when_model_unavailable` | friendly 503 |
| TC-I08 | `test_health_ok`, `test_health_degraded_when_model_down` | health semantics |
| TC-I09 | `test_predict_contract` | response schema, model version, id |
| TC-I10 | `test_feedback_stored_encrypted`, `test_feedback_rejects_unknown_category` | feedback path |
| TC-I11 | `test_batch_predict_and_limit` | batch + limit 50 |
| TC-I12 | `test_categories_and_examples` | reference endpoints |
| TC-I13 | `test_pipeline_endpoints` | DAG edges from dvc.yaml, run summary, reports |
| TC-I14 | `test_retrain_requires_admin_token` | 401 without / with a wrong token |
| TC-I15 | `test_drift_endpoint_reports_collecting_then_stable` | drift status before reference |
| TC-I16 | `test_metrics_exposed` | all metric families exported |

### End-to-end (tests/e2e) - 6 cases

| ID | Test | Expectation |
|---|---|---|
| TC-E01 | `test_frontend_served_and_configured` | UI + runtime config served |
| TC-E02 | `test_backend_healthy_with_model` | champion loaded |
| TC-E03 | `test_routing_examples_land_in_expected_teams` | 4 canonical complaints routed correctly |
| TC-E04 | `test_severe_complaint_flagged_urgent` | foreclosure complaint escalated with reason |
| TC-E05 | `test_latency_under_one_second` | AC-5 |
| TC-E06 | `test_prometheus_scrapes_all_targets` | every component monitored |

## 5. Manual test scenarios

| ID | Steps | Expected |
|---|---|---|
| M-1 | First-time user opens `http://<vm>:8080`, clicks an example chip | Result card in ~1 s showing team, confidence, priority, reasons and similar cases |
| M-2 | Type 10 characters | Button disabled, hint "Please write a bit more" |
| M-3 | `docker compose stop model-server`, then route | Red status dot "Model offline"; clear error message, no crash |
| M-4 | Send a correction | Toast "Thank you…"; buttons disabled; `feedback.enc.jsonl` grows and is unreadable as text |
| M-5 | Pipeline console | DAG coloured by last status; failures listed with error; registry shows @champion |
| M-6 | `make drift`, wait ~2 min | Drift KPI red → Alertmanager shows `DataDriftDetected` → retrainer history shows `drift_alert` run → new version appears (promoted or rejected by the gate) |
| M-7 | `make rollback VERSION=1` | Within ~20 s `/health` reports model_version 1 |
| M-8 | Resize the browser to phone width | Single-column layout, no horizontal scroll |
| M-9 | Retrain with a wrong admin token | "Retraining not started: Invalid or missing admin token" |

## 6. Environment

Ubuntu 22.04/24.04 VM (≥ 4 vCPU, ≥ 8 GB RAM, ≥ 25 GB disk), Docker Engine 24+, compose v2, Python 3.10+ venv for running tests on the host.

## 7. Entry / exit criteria

Entry: `make lint` clean and the stack builds. Exit: AC-1 … AC-9 satisfied; the test report is attached in `docs/test_report.md`.
