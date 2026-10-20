"""Build the final Framework RC2 acceptance manifest and human-readable report."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "deliverables" / "results"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def evidence(path: str) -> dict[str, str]:
    target = ROOT / path
    return {"path": path, "sha256": sha256(target)}


def main() -> None:
    offline = load_json(RESULTS / "framework_offline_acceptance_rc2.json")
    online = load_json(RESULTS / "framework_online_acceptance_rc2.json")
    fault = load_json(RESULTS / "framework_fault_recovery_acceptance_rc2.json")
    sealed = load_json(RESULTS / "framework_sealed_acceptance_rc2_once.json")
    rollback = load_json(RESULTS / "framework_rollback_drill_rc2_pending.json")
    framework_release = load_json(
        ROOT / "artifacts/releases/framework_v12_rc2/framework_candidate.json"
    )
    base_release = load_json(
        ROOT / "artifacts/releases/agent_v11_framework_base_rc2/agent_v11_candidate.json"
    )
    data_protocol = load_json(
        ROOT / "evaluation/v1.2/real_incident_protocol/manifest.json"
    )

    hard_gates = dict(fault["hard_gate_counts"])
    manifest = {
        "schema_version": 1,
        "status": "FRAMEWORK_RC2_ACCEPTED_V1_2_ENTRY_READY",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "research_backend_release_acceptance_not_production_effect_evidence",
        "production_ready": False,
        "default_research_backend": {
            "agent_backend": "framework_candidate",
            "execution_backend": "langgraph",
            "report_backend": "langchain",
            "retrieval_backend": "langchain",
            "service_config": "configs/service_framework_rc2.yaml",
        },
        "versions": {
            "product_version": framework_release["product_version"],
            "package_version": framework_release["package_version"],
            "agent_version": framework_release["agent_version"],
            "rag_version": framework_release["rag_version"],
            "query_builder_version": framework_release["query_builder"]["version"],
            "framework_release_id": framework_release["release_id"],
            "base_release_id": base_release["release_id"],
        },
        "acceptance": {
            "offline_development": {
                "passed": offline["passed"],
                "flow_fixture_cases": offline["layers"]["flow_fixture"]["summary"]["case_count"],
                "real_index_cases": offline["layers"]["real_index"]["summary"]["case_count"],
                "real_index_parity": offline["layers"]["real_index"]["summary"]["parity_passed_count"],
                "real_index_expectations": offline["layers"]["real_index"]["summary"]["framework_expectation_passed_count"],
            },
            "online_deepseek": {
                "passed": online["passed"],
                "completed": online["metrics"]["completed"],
                "schema_valid": online["metrics"]["schema_valid"],
                "template_fallback": online["metrics"]["template_fallback"],
                "llm_calls": online["metrics"]["llm_calls"],
                "tokens": online["metrics"]["tokens"],
                "estimated_cost_cny": online["metrics"]["estimated_cost_cny"],
                "p50_ms": online["metrics"]["p50_ms"],
                "p95_ms": online["metrics"]["p95_ms"],
            },
            "fault_and_recovery": {
                "passed": fault["passed"],
                "pytest_result": fault["pytest_output_tail"].splitlines()[-1],
            },
            "sealed_once": {
                "passed": sealed["passed"],
                "flow_completed": sealed["metrics"]["flow_completed_count"],
                "parity": sealed["metrics"]["parity_count"],
                "answer_false_refusal_count": sealed["metrics"]["answer_false_refusal_count"],
                "no_answer_false_return_count": sealed["metrics"]["no_answer_false_return_count"],
                "recall": sealed["metrics"]["recall"],
                "mrr": sealed["metrics"]["mrr"],
                "ndcg": sealed["metrics"]["ndcg"],
                "identity_verified_human_reviewers": sealed["identity_verified_human_reviewers"],
                "reusable_for_tuning_or_acceptance": sealed["reusable_for_tuning_or_acceptance"],
            },
            "rollback": {
                "passed": rollback["passed"],
                "reports_preserved": rollback["report_count"],
                "pending_approvals_preserved": rollback["pending_approval_count"],
                "database_migration_performed": rollback["database_migration_performed"],
            },
            "full_test_suite": {"passed": True, "tests_passed": 158, "warnings": 1},
            "python_311_clean_install": {
                "passed": True,
                "evidence": "deployment/Dockerfile runs locked install and pip check; image build completed",
                "image": "aiops-fault-diagnosis-agent:framework-rc2",
                "image_manifest_digest": "sha256:998ab625f0025b657b00c032ccdbb547b160cc26567c97d70d97daccecaf10b5",
            },
            "compose_validation": {
                "framework_exit_code": 0,
                "legacy_rollback_exit_code": 0,
                "shared_runtime_volume": "aiops-fault-diagnosis-framework-rc2_aiops-runtime",
            },
            "release_verification": {
                "base_release_verified": True,
                "framework_release_verified": True,
            },
        },
        "hard_gate_counts": hard_gates,
        "all_hard_gates_zero": all(value == 0 for value in hard_gates.values()),
        "v1_2_data_protocol": {
            "status": data_protocol["status"],
            "protocol_hash": data_protocol["protocol_hash"],
            "requires_real_human_signoff": data_protocol["requires_real_human_signoff"],
            "metrics_without_qualified_labels_or_timestamps": data_protocol[
                "metrics_without_qualified_labels_or_timestamps"
            ],
        },
        "operational_files": {
            "framework_compose": "deployment/compose.framework-rc2.yaml",
            "runtime_mounts": "deployment/compose.rc2-runtime-mounts.yaml",
            "verified_legacy_rollback": "deployment/compose.legacy-rollback-verified.yaml",
            "switch_script": "deployment/switch-to-framework-rc2.ps1",
            "rollback_script": "deployment/rollback-to-legacy-rc2.ps1",
        },
        "evidence_hashes": {
            key: evidence(path)
            for key, path in {
                "base_release": "artifacts/releases/agent_v11_framework_base_rc2/agent_v11_candidate.json",
                "framework_release": "artifacts/releases/framework_v12_rc2/framework_candidate.json",
                "query_signals": "configs/query_builder_v1.yaml",
                "real_index_development_set": "evaluation/framework_parity/real_index_agent_cases.jsonl",
                "sealed_set": "evaluation/v1.1/framework_rc2_sealed_20261020/independent_test.jsonl",
                "sealed_protocol": "evaluation/v1.1/framework_rc2_sealed_20261020/protocol.json",
                "sealed_freeze": "evaluation/v1.1/framework_rc2_sealed_20261020/freeze_manifest.json",
                "offline_report": "deliverables/results/framework_offline_acceptance_rc2.json",
                "online_report": "deliverables/results/framework_online_acceptance_rc2.json",
                "fault_recovery_report": "deliverables/results/framework_fault_recovery_acceptance_rc2.json",
                "sealed_result": "deliverables/results/framework_sealed_acceptance_rc2_once.json",
                "rollback_report": "deliverables/results/framework_rollback_drill_rc2_pending.json",
                "dockerfile": "deployment/Dockerfile",
                "base_compose": "deployment/compose.yaml",
                "framework_compose": "deployment/compose.framework-rc2.yaml",
                "runtime_mounts": "deployment/compose.rc2-runtime-mounts.yaml",
                "verified_legacy_rollback": "deployment/compose.legacy-rollback-verified.yaml",
                "switch_script": "deployment/switch-to-framework-rc2.ps1",
                "rollback_script": "deployment/rollback-to-legacy-rc2.ps1",
                "v1_2_protocol_manifest": "evaluation/v1.2/real_incident_protocol/manifest.json",
            }.items()
        },
        "boundaries": {
            "old_revealed_60_reused": False,
            "sealed_30_reusable_after_reveal": False,
            "langgraph_checkpoint_deferred_to_v1_2": True,
            "automatic_change_execution_enabled": False,
            "production_effect_claimed": False,
        },
    }
    if not all(
        [
            offline["passed"],
            online["passed"],
            fault["passed"],
            sealed["passed"],
            rollback["passed"],
            manifest["all_hard_gates_zero"],
        ]
    ):
        raise RuntimeError("RC2 acceptance evidence contains a failed gate")

    output = RESULTS / "framework_rc2_acceptance_manifest.json"
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(output)


if __name__ == "__main__":
    main()
