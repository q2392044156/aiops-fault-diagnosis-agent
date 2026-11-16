# 自动化测试

## 模块职责

验证数据、检测、检索、诊断、服务、发布和恢复行为。

## 依赖边界

测试可依赖所有业务模块，生产代码不得反向依赖测试。

部分用例依赖本地发布制品（`artifacts/releases`）与 PyTorch：缺失时由 `conftest.py` 自动跳过，CI 中显示为 skipped，本地构建制品后会自动执行。

## Python 文件说明

| 文件 | 主要功能 | 主要类或函数 |
| --- | --- | --- |
| `conftest.py` | 为依赖本地发布制品的用例提供统一的跳过策略。 | `requires_artifacts` |
| `test_architecture.py` | 验证离线/在线一级目录和二级入口可导入。 | `test_offline_online_architecture_is_importable` |
| `test_adapters.py` | 验证 HDFS_v1 / Docker / WSL 适配器与 canonical schema。 | `test_hdfs_v1_adapter_maps_fields`、`test_real_lab_logs_parse_rate` |
| `test_source_templates.py` | 验证按来源构建与加载 Drain3 模板。 | `test_build_and_match_source_templates` |
| `test_events.py` | 验证门禁打分与事件构建。 | `test_gate_passes_error_rows`、`test_build_event_keeps_gate_provenance` |
| `test_source_detector.py` | 验证模板新颖度检测器。 | `test_novelty_detector_separates_templates` |
| `test_windows.py` | 验证独立正常窗口的切分。 | `test_normal_windows_split_by_lines` |
| `test_evidence.py` | 验证证据级关键行规则。 | `test_volume_gold_matches_no_space` |
| `test_evaluate_unified.py` | 验证统一评测的案例口径与 cluster bootstrap。 | `test_bootstrap_is_deterministic_and_bounded`、`test_bootstrap_marks_perfect_case_rate_as_boundary` |
| `test_signals.py` | 验证可解释根因信号的同义表述、干扰排序、证据去重与窗口合并。 | `test_heartbeat_paraphrase_is_detected`、`test_heartbeat_signal_beats_volume_distractor`、`test_wsl_failed_volumes_is_detected`、`test_safe_mode_paraphrase_is_detected`、`test_network_signal_beats_heartbeat_noise`、`test_rank_root_causes_follows_log_signal`、`test_evidence_dedupes_numeric_variants`、`test_merge_passing_merges_overlapping_windows`、`test_merge_passing_respects_max_span` |
| `test_challenge20.py` | 验证回归集的均衡分组、holdout 隔离、同义改写和报告解析。 | `test_manifest_has_four_balanced_groups_and_complete_cases`、`test_source_cases_are_holdout_from_unified4` |
| `test_network_confusion.py` | 验证网络分区与心跳丢失的判别规则。 | `test_network_partition_wins_when_datanode_is_retrying` |
| `test_agent.py` | 验证 agent 相关功能、边界和回归行为。 | `V11EvalLedger`、`V11EvalClient`、`test_v11_online_report_evaluation_runs_three_release_bound_rounds`、`test_v11_online_report_evaluation_requires_configured_client`、`candidate_calibration`、`seed_event`、`budget`、`test_adev_is_fixed_and_deterministic` 等 |
| `test_candidate_pool_v11.py` | 验证 candidate pool v11 相关功能、边界和回归行为。 | `_reviewed_rows`、`_write_rows`、`test_public_candidate_pool_is_blinded_complete_and_nonduplicate`、`test_public_candidate_packet_builder_refuses_overwrite`、`test_public_candidate_pool_rejects_label_leak`、`test_public_candidate_pool_accepts_complete_external_review_structure`、`test_reviewed_candidate_pool_freezes_to_release_ready_protocol`、`test_review_disagreement_cannot_be_frozen` |
| `test_redteam.py` | 验证红队用例全部拦截且不误杀正常样本。 | `test_redteam_blocks_all_attacks_without_false_positives` |
| `test_lab.py` | 验证路线 A 的实验编排、incident 合法性与指标计算。 | `test_dry_run_generates_valid_incident`、`test_incident_metrics_rank_and_mttd` |
| `test_mcp.py` | 验证 MCP 握手、工具清单、调用与参数校验。 | `test_mcp_initialize_and_list`、`test_mcp_call_returns_text_and_rejects_bad_input` |
| `test_tracing.py` | 验证 span 落库、父子关系与空实现降级。 | `test_tracer_records_parent_and_attributes`、`test_tracer_disabled_without_database_support` |
| `test_context_builder.py` | 验证上下文预算、压缩策略与引擎集成。 | `test_full_strategy_keeps_every_evidence`、`test_compressed_strategy_respects_budget_and_keeps_kinds`、`test_engine_generate_uses_context_strategy` |
| `test_trajectory.py` | 验证轨迹指标、失败分类、汇总与 pass^k。 | `test_clean_run_has_no_flags`、`test_retry_loop_is_detected`、`test_failed_tool_with_report_is_recovered`、`test_aggregate_and_pass_pow_k` |
| `test_router_v2.py` | 验证受控路由、工具 Schema、指标仓库与工具调用客户端。 | `test_specs_expose_function_definitions`、`test_router_keeps_allowed_blocks_unknown_and_bad_json`、`test_metrics_store_window_and_stats`、`test_client_parses_tool_calls` |
| `test_coverage_v11.py` | 验证 coverage v11 相关功能、边界和回归行为。 | `test_agent_coverage_comparison_requires_sealed_inputs` |
| `test_download.py` | 验证 download 相关功能、边界和回归行为。 | `Response`、`test_download`、`test_wrong_hash_and_range`、`test_zip`、`test_extract_allowlist`、`test_retry_and_existing`、`test_download_lock` |
| `test_framework_v12.py` | 验证 framework v12 相关功能、边界和回归行为。 | `FakeRetriever`、`_budget`、`_evidence`、`test_framework_dependencies_have_an_independent_exact_lock`、`test_langchain_retriever_preserves_raw_search_and_release_metadata`、`test_langchain_retriever_keeps_fail_closed_empty_result`、`test_langchain_summary_chain_uses_audited_callback_and_strict_parser`、`test_candidate_langchain_backend_repairs_once_through_existing_llm_budget_path` 等 |
| `test_lstm.py` | 验证 lstm 相关功能、边界和回归行为。 | `_item`、`test_contiguous_chunk_boundaries_keep_the_complete_session`、`test_empty_and_misaligned_sequences_are_rejected`、`test_padding_does_not_change_cpu_prediction`、`test_padding_does_not_change_cuda_prediction`、`test_group_role_is_deterministic_and_label_independent`、`test_pos_weight_uses_only_current_training_members`、`test_lstm_test_split_is_sealed_before_artifact_access` 等 |
| `test_modeling.py` | 验证 modeling 相关功能、边界和回归行为。 | `test_event_proxy_clustering_gap_span_and_singletons`、`test_sampling_ignores_labels_and_keeps_groups_complete`、`test_redaction_and_feature_document_exclude_forbidden_values`、`test_frozen_match_does_not_create_templates`、`test_metrics_and_constrained_threshold_boundary`、`test_isolation_features_have_only_declared_numeric_values`、`test_test_prediction_is_sealed_before_artifact_access`、`test_manifest_tamper_is_rejected` |
| `test_offline_framework_comparison.py` | 验证 offline framework comparison 相关功能、边界和回归行为。 | `test_development_case_set_is_explicitly_non_independent`、`test_case_loader_rejects_unlabelled_acceptance_data`、`test_offline_fixture_never_returns_untrusted_case_text`、`test_structural_diff_reports_exact_path`、`test_offline_comparison_runs_real_retrieval_and_both_agent_paths` |
| `test_pipeline.py` | 验证 pipeline 相关功能、边界和回归行为。 | `test_parser`、`test_bad`、`dataset`、`test_end_to_end`、`test_crossing_group`、`test_bad_session_and_budget`、`test_tamper_rejected`、`test_relocated_rebuild` 等 |
| `test_project_structure.py` | 验证功能目录、模块说明和中文源码注释的完整性。 | `test_modular_project_structure_is_complete` |
| `test_query_builder_v11.py` | 验证 query builder v11 相关功能、边界和回归行为。 | `builder`、`test_query_builder_is_deterministic_and_uses_only_allowlisted_terms`、`test_query_builder_stably_ranks_components_and_caps_at_three`、`test_query_builder_rejects_untrusted_component_and_invalid_version`、`test_query_builder_uses_component_default_without_signal` |
| `test_rag.py` | 验证 rag 相关功能、边界和回归行为。 | `FakeRetriever`、`FakeClient`、`config`、`valid_body`、`test_no_evidence_never_calls_model`、`test_valid_generation_has_traceable_citations`、`test_unauthorized_citation_repairs_once_then_degrades`、`test_invalid_json_usage_is_counted_and_repaired_once` 等 |
| `test_retrieval.py` | 验证 retrieval 相关功能、边界和回归行为。 | `retrieval_cfg`、`test_corpus_and_query_protocol_are_complete_and_isolated`、`test_development_validation_does_not_parse_sealed_rtest`、`test_bm25_and_tokenizer_preserve_operational_terms`、`test_rrf_uses_ranks_not_raw_scores`、`_Encoder`、`test_retriever_gate_and_version_filter`、`test_gate_calibration_uses_query_product_version` 等 |
| `test_retrieval_protocol_v11.py` | 验证 retrieval protocol v11 相关功能、边界和回归行为。 | `_write_jsonl`、`_protocol`、`test_v11_protocol_requires_sealed_cross_time_version_independent_review`、`test_v11_protocol_refuses_small_reviewed_test`、`test_v11_protocol_rejects_leakage_and_unreviewed_release`、`test_public_apache_candidate_is_structurally_valid_but_not_a_blind_release_set`、`test_blind_evaluator_does_not_open_current_unreviewed_test_or_write_result`、`test_blind_evaluator_writes_immutable_release_bound_comparison` 等 |
| `test_review_v11.py` | 验证 review v11 相关功能、边界和回归行为。 | `_write`、`test_review_packet_hides_proposals_and_covers_pool`、`test_review_submission_checks_evidence_scope_and_keeps_disagreements` |
| `test_runbook_review_v11.py` | 验证 runbook review v11 相关功能、边界和回归行为。 | `_write_jsonl`、`test_blind_packet_and_sealed_relevance_scoring` |
| `test_selection.py` | 验证 selection 相关功能、边界和回归行为。 | `test_weighted_ap_matches_sklearn`、`test_group_paired_bootstrap_is_deterministic`、`test_shuffle_ablation_is_stable_and_preserves_membership`、`test_lstm_can_remove_safe_feature_branch`、`test_stage_manifest_tamper_is_rejected` |
| `test_service.py` | 验证 service 相关功能、边界和回归行为。 | `FakeModel`、`config`、`runtime`、`DummyUpload`、`upload`、`drive`、`test_database_idempotency_and_recovery`、`test_four_concurrent_submissions_create_one_task` 等 |
| `test_v12_runtime.py` | 验证 v12 runtime 相关功能、边界和回归行为。 | `_jsonl`、`_trace_snapshot`、`_label`、`test_external_snapshot_import_is_idempotent_and_keeps_labels_out`、`test_database_checkpointer_survives_new_graph_instance`、`_incident`、`test_real_incident_lifecycle_keeps_unqualified_metrics_na` |
| `test_w10.py` | 验证 w10 相关功能、边界和回归行为。 | `FakeLedger`、`SafeClient`、`test_atest_protocol_is_fixed_complete_and_isolated`、`test_atest_replay_meets_safety_gates`、`test_atest_three_online_runs_are_recorded`、`test_atest_rejects_invalid_repeat`、`test_release_configuration_binds_v1_components` |
| `test_w6.py` | 验证 w6 相关功能、边界和回归行为。 | `create`、`test_schema_v1_migrates_idempotently`、`test_queue_capacity_allows_duplicates_but_rejects_new_tasks`、`test_lease_expiry_recovery_and_fencing`、`test_worker_heartbeat_and_operation_summary`、`test_ui_client_uses_only_http_api` |

## 阅读建议

先阅读配置或 Schema，再阅读核心引擎，最后查看 `workflow.py`、`__main__.py` 或验收脚本了解完整调用顺序。文件内的中文注释重点解释职责、输入参数、数据字段和关键约束。
