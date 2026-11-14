# Test Report - Financial Complaint Router

Generated: 2026-11-14 22:34 from `reports/tests/junit.xml` (see docs/test_plan.md for the plan and acceptance criteria).

## Summary

| Total | Passed | Failed | Skipped | Duration |
|---|---|---|---|---|
| 64 | 64 | 0 | 0 | 40.7 s |

## Acceptance criteria

| ID | Criterion | Evidence | Result |
|---|---|---|---|
| AC-1 | All automated tests pass | 64 tests (list below) | **MET** |
| AC-2 | Test macro-F1 >= 0.70 | macro-F1 = 0.801 (reports/metrics.json) | **MET** |
| AC-3 | Urgent recall >= 0.65 and flag rate <= 35 % | recall = 0.741, flag rate = 31.2% | **MET** |
| AC-4 | A worse retrained model is not deployed | TC-I04 | **MET** |
| AC-5 | Prediction latency < 1 s | 28 ms per prediction (evaluate stage) | **MET** |
| AC-6 | Bad input gives 422, model down gives a clear 503 | TC-I06, TC-I07 | **MET** |
| AC-7 | Complaint text is stored only encrypted | TC-U35, TC-I10 | **MET** |
| AC-8 | Drift triggers retraining automatically | manual scenario M-6 (`make drift`) | **Manual** |
| AC-9 | A non-technical user can route a complaint | manual scenario M-1 | **Manual** |

## Test cases

| Module | Test | Result | Time (s) | Detail |
|---|---|---|---|---|
| integration.test_api | `test_health_ok` | PASS | 0.11 |  |
| integration.test_api | `test_health_degraded_when_model_down` | PASS | 0.04 |  |
| integration.test_api | `test_predict_contract` | PASS | 0.06 |  |
| integration.test_api | `test_predict_rejects_invalid_input[payload0]` | PASS | 0.05 |  |
| integration.test_api | `test_predict_rejects_invalid_input[payload1]` | PASS | 0.05 |  |
| integration.test_api | `test_predict_rejects_invalid_input[payload2]` | PASS | 0.06 |  |
| integration.test_api | `test_predict_rejects_invalid_input[payload3]` | PASS | 0.06 |  |
| integration.test_api | `test_predict_rejects_invalid_input[payload4]` | PASS | 0.04 |  |
| integration.test_api | `test_predict_returns_503_when_model_unavailable` | PASS | 0.05 |  |
| integration.test_api | `test_batch_predict_and_limit` | PASS | 0.06 |  |
| integration.test_api | `test_feedback_stored_encrypted` | PASS | 0.05 |  |
| integration.test_api | `test_feedback_rejects_unknown_category` | PASS | 0.06 |  |
| integration.test_api | `test_categories_and_examples` | PASS | 0.07 |  |
| integration.test_api | `test_pipeline_endpoints` | PASS | 0.07 |  |
| integration.test_api | `test_retrain_requires_admin_token` | PASS | 0.05 |  |
| integration.test_api | `test_drift_endpoint_reports_collecting_then_stable` | PASS | 0.04 |  |
| integration.test_api | `test_metrics_exposed` | PASS | 0.05 |  |
| integration.test_pipeline_end_to_end | `test_full_pipeline_on_sample` | PASS | 24.49 |  |
| integration.test_pipeline_end_to_end | `test_run_log_records_every_stage` | PASS | 0.00 |  |
| integration.test_pipeline_end_to_end | `test_logged_pyfunc_model_serves_predictions` | PASS | 0.55 |  |
| integration.test_pipeline_end_to_end | `test_second_worse_candidate_is_not_promoted` | PASS | 14.34 |  |
| integration.test_pipeline_end_to_end | `test_backend_registry_client_reads_real_registry` | PASS | 0.09 |  |
| unit.test_categories | `test_every_mapped_product_targets_a_known_category` | PASS | 0.00 |  |
| unit.test_categories | `test_nine_categories_with_teams` | PASS | 0.00 |  |
| unit.test_categories | `test_map_product_handles_legacy_names_and_unknowns` | PASS | 0.00 |  |
| unit.test_categories | `test_priority_issue_rule` | PASS | 0.00 |  |
| unit.test_categories | `test_urgent_keywords_detected_once_in_order` | PASS | 0.00 |  |
| unit.test_drift | `test_psi_zero_for_identical_distributions` | PASS | 0.01 |  |
| unit.test_drift | `test_psi_grows_with_shift` | PASS | 0.00 |  |
| unit.test_drift | `test_histogram_and_distribution_normalised` | PASS | 0.00 |  |
| unit.test_drift | `test_no_drift_on_reference_like_traffic` | PASS | 0.00 |  |
| unit.test_drift | `test_drift_detected_on_new_vocabulary_and_skewed_categories` | PASS | 0.00 |  |
| unit.test_pipeline_logic | `test_validation_passes_on_good_data` | PASS | 0.01 |  |
| unit.test_pipeline_logic | `test_validation_fails_on_unknown_label_and_missing_column` | PASS | 0.01 |  |
| unit.test_pipeline_logic | `test_balanced_sample_caps_and_drops` | PASS | 0.03 |  |
| unit.test_pipeline_logic | `test_split_is_stratified_and_disjoint` | PASS | 0.02 |  |
| unit.test_pipeline_logic | `test_promotion_gate[metrics0-None-True]` | PASS | 0.00 |  |
| unit.test_pipeline_logic | `test_promotion_gate[metrics1-None-False]` | PASS | 0.00 |  |
| unit.test_pipeline_logic | `test_promotion_gate[metrics2-None-False]` | PASS | 0.00 |  |
| unit.test_pipeline_logic | `test_promotion_gate[metrics3-0.84-False]` | PASS | 0.00 |  |
| unit.test_pipeline_logic | `test_promotion_gate[metrics4-0.84-True]` | PASS | 0.00 |  |
| unit.test_pipeline_logic | `test_promotion_gate[metrics5-None-False]` | PASS | 0.01 |  |
| unit.test_pipeline_logic | `test_stage_run_logs_success_and_failure` | PASS | 0.04 |  |
| unit.test_pipeline_logic | `test_feedback_is_encrypted_and_reloadable` | PASS | 0.01 |  |
| unit.test_pipeline_logic | `test_feedback_refused_without_key` | PASS | 0.00 |  |
| unit.test_router_model | `test_predicts_expected_categories` | PASS | 0.00 |  |
| unit.test_router_model | `test_output_contract` | PASS | 0.00 |  |
| unit.test_router_model | `test_explanation_terms_relate_to_text` | PASS | 0.00 |  |
| unit.test_router_model | `test_severe_keywords_always_escalate` | PASS | 0.01 |  |
| unit.test_router_model | `test_priority_decision_rule` | PASS | 0.00 |  |
| unit.test_router_model | `test_priority_threshold_tuned_in_range` | PASS | 0.00 |  |
| unit.test_router_model | `test_oov_rate` | PASS | 0.00 |  |
| unit.test_router_model | `test_save_load_roundtrip` | PASS | 0.04 |  |
| unit.test_router_model | `test_alternative_model_types[sgd]` | PASS | 0.02 |  |
| unit.test_router_model | `test_alternative_model_types[cnb]` | PASS | 0.02 |  |
| unit.test_router_model | `test_invalid_usage` | PASS | 0.00 |  |
| unit.test_text_cleaning | `test_redaction_tokens_removed` | PASS | 0.00 |  |
| unit.test_text_cleaning | `test_money_amount_tagged` | PASS | 0.00 |  |
| unit.test_text_cleaning | `test_pii_is_masked` | PASS | 0.00 |  |
| unit.test_text_cleaning | `test_lowercase_and_whitespace` | PASS | 0.00 |  |
| unit.test_text_cleaning | `test_non_string_input_returns_empty` | PASS | 0.00 |  |
| unit.test_text_cleaning | `test_truncation` | PASS | 0.00 |  |
| unit.test_text_cleaning | `test_clean_records_maps_labels_and_filters` | PASS | 0.01 |  |
| unit.test_text_cleaning | `test_clean_records_empty_batch` | PASS | 0.00 |  |
