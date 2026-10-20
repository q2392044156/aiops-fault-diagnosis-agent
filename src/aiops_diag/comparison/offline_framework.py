"""Offline parity comparison for the legacy and framework candidate paths.

This module is deliberately outside ``framework_v12`` so running or improving
the development harness does not mutate the frozen framework candidate hash.
"""

from __future__ import annotations

import json
import math
import shutil
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from aiops_diag.agent.release import TOOLS
from aiops_diag.data.common import digest, key
from aiops_diag.service.config import load as load_service
from aiops_diag.service.runtime import ServiceRuntime


TERMINAL = {"WAITING_REVIEW", "COMPLETED", "APPROVED_REPORT", "FAILED"}
BACKENDS = ("legacy", "framework_candidate")
LOG_SCHEMA = pa.schema([
    ("log_id", pa.string()),
    ("timestamp", pa.string()),
    ("level", pa.string()),
    ("component", pa.string()),
    ("redacted_message", pa.string()),
    ("template_id", pa.string()),
    ("session_ids", pa.list_(pa.string())),
])


class OfflineSummaryClient:
    """Deterministic provider substitute; it never performs network I/O."""

    configured = True

    def __init__(self):
        self.calls = 0

    def complete_json(self, _messages):
        self.calls += 1
        return ({"summary": "现有只读证据支持一个待验证候选，仍需人工结合独立观测确认。"},
                {"input_tokens": 64, "output_tokens": 24,
                 "estimated_cost_cny": 0.0})

    def close(self):
        return None


class OfflineCaseRetriever:
    """Deterministic evidence boundary used only by synthetic Agent cases."""

    def __init__(self, manifest: dict, status: str):
        self.manifest = manifest
        self.status = status

    def verify_integrity(self):
        return True

    def public(self):
        return {"kb_release_id": self.manifest["kb_release_id"],
                "offline_fixture": self.status}

    def chunk(self, chunk_id):
        return {"chunk_id": chunk_id} if chunk_id == "chk_offline_fixture" else None

    def search(self, query, mode=None, top_k=None, component=None,
               product_version=None, apply_gate=True):
        items = []
        if self.status == "evidence_found":
            items = [{
                "chunk_id": "chk_offline_fixture",
                "doc_id": "offline-flow-fixture",
                "title": "离线流程验证证据",
                "section_path": "evidence",
                "source_url": "offline://development-fixture",
                "source_version": "development-only",
                "component": [component] if component else [],
                "text": "仅用于验证框架迁移流程的固定只读证据，不代表真实根因。",
                "rrf_score": 1.0,
                "dense_score": 0.99,
                "bm25_score": 1.0,
            }]
        return {"status": self.status, "mode": mode or "hybrid", "items": items,
                "gate_score": 0.99 if items else 0.0,
                "gate_strategy": "offline_development_fixture"}


def _json_lines(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on line {number}: {exc}") from exc
    return rows


def load_cases(path: str | Path) -> list[dict]:
    """Load and validate the mutable development-only comparison set."""
    path = Path(path)
    rows = _json_lines(path)
    if not rows:
        raise ValueError("Comparison case set is empty")
    seen = set()
    for row in rows:
        case_id = row.get("case_id")
        if (not isinstance(case_id, str) or not case_id
                or case_id in seen):
            raise ValueError("case_id values must be non-empty and unique")
        seen.add(case_id)
        if row.get("schema_version") != 1:
            raise ValueError(f"{case_id}: unsupported schema_version")
        if row.get("source") not in {
                "developer_regression", "synthetic_redacted_development",
                "real_index_synthetic_development"}:
            raise ValueError(f"{case_id}: case source is not development-only")
        case_type = row.get("case_type")
        if case_type == "retrieval":
            if not isinstance(row.get("query"), str) or not row["query"].strip():
                raise ValueError(f"{case_id}: retrieval query is required")
            if row.get("expected_status") not in {
                    "evidence_found", "insufficient_evidence"}:
                raise ValueError(f"{case_id}: invalid expected_status")
        elif case_type == "agent":
            if row.get("mode") not in {"auto", "template"}:
                raise ValueError(f"{case_id}: invalid agent mode")
            if not isinstance(row.get("logs"), list):
                raise ValueError(f"{case_id}: logs must be a list")
            if row.get("retrieval_fixture") not in {
                    "evidence_found", "insufficient_evidence", "live"}:
                raise ValueError(f"{case_id}: invalid retrieval_fixture")
            for log in row["logs"]:
                if not all(isinstance(log.get(name), str) for name in (
                        "level", "component", "message", "template_id")):
                    raise ValueError(f"{case_id}: incomplete synthetic log")
            if not isinstance(row.get("expected_review_reasons"), list):
                raise ValueError(f"{case_id}: expected_review_reasons is required")
        else:
            raise ValueError(f"{case_id}: unsupported case_type")
    return rows


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _retrieval_snapshot(result: dict) -> dict:
    return {
        "status": result.get("status"),
        "mode": result.get("mode"),
        "gate_score": _finite(result.get("gate_score")),
        "gate_strategy": result.get("gate_strategy"),
        "items": [{name: _finite(item.get(name)) for name in (
            "chunk_id", "doc_id", "section_path", "source_version",
            "rrf_score", "dense_score", "bm25_score")}
            for item in result.get("items", [])],
    }


def _diff(left: Any, right: Any, path: str = "$") -> list[dict]:
    if type(left) is not type(right):
        return [{"path": path, "legacy": left, "framework_candidate": right}]
    if isinstance(left, dict):
        differences = []
        for name in sorted(set(left) | set(right)):
            if name not in left or name not in right:
                differences.append({"path": f"{path}.{name}",
                                    "legacy": left.get(name, "<missing>"),
                                    "framework_candidate": right.get(name, "<missing>")})
            else:
                differences.extend(_diff(left[name], right[name], f"{path}.{name}"))
        return differences
    if isinstance(left, list):
        if len(left) != len(right):
            return [{"path": path + ".length", "legacy": len(left),
                     "framework_candidate": len(right)}]
        differences = []
        for index, (legacy, framework) in enumerate(zip(left, right, strict=True)):
            differences.extend(_diff(legacy, framework, f"{path}[{index}]"))
        return differences
    if isinstance(left, float):
        equal = math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-12)
    else:
        equal = left == right
    return [] if equal else [{"path": path, "legacy": left,
                              "framework_candidate": right}]


def _runtime(config_path: Path, work_dir: Path) -> ServiceRuntime:
    cfg = load_service(config_path)
    cfg["paths"]["runtime_dir"] = str(work_dir)
    cfg["paths"]["database"] = str(work_dir / "service.sqlite3")
    runtime = ServiceRuntime(cfg, role="worker")
    if runtime.ready_error:
        runtime.stop()
        raise RuntimeError(f"Unable to load {config_path.name}: {runtime.ready_error}")
    runtime.agent.client = OfflineSummaryClient()
    runtime._comparison_base_retriever = runtime.retriever
    return runtime


def _seed_agent_case(runtime: ServiceRuntime, case: dict, artifact_root: Path) -> str:
    case_hash = key(case["case_id"])
    batch_id = "bat_cmp_" + case_hash[:20]
    event_id = "evt_cmp_" + case_hash[:20]
    session_id = "ses_cmp_" + case_hash[:20]
    directory = artifact_root / case["case_id"]
    directory.mkdir(parents=True, exist_ok=False)
    stamp = "2026-10-20T00:00:00+00:00"
    rows = []
    for index, item in enumerate(case["logs"], 1):
        rows.append({
            "log_id": f"log_{case_hash[:16]}_{index:02d}",
            "timestamp": f"2026-10-20T00:00:{index:02d}+00:00",
            "level": item["level"],
            "component": item["component"],
            "redacted_message": item["message"],
            "template_id": item["template_id"],
            "session_ids": [session_id],
        })
    table = pa.Table.from_pylist(rows, schema=LOG_SCHEMA)
    pq.write_table(table, directory / "logs.parquet")
    with runtime.db.transaction() as db:
        db.execute(
            "INSERT INTO batches(batch_id,source_kind,source_ref,input_hash,release_id,"
            "processing_hash,status,artifact_dir,total_lines,parsed_lines,session_count,"
            "anomaly_count,event_count,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (batch_id, "comparison", case["case_id"], case_hash,
             runtime.manifest["release_id"], "development-parity", "SUCCEEDED",
             str(directory), len(rows), len(rows), 1, 1, 1, stamp, stamp))
        db.execute(
            "INSERT INTO sessions(batch_id,session_id,start_time,end_time,line_count,"
            "unknown_count,anomaly_score,threshold,prediction,first_log_id,last_log_id,"
            "host_alias) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (batch_id, session_id, stamp, stamp, len(rows), 0, 5.0, 4.0, 1,
             rows[0]["log_id"] if rows else None,
             rows[-1]["log_id"] if rows else None, "host-redacted"))
        db.execute(
            "INSERT INTO events(event_id,batch_id,host_alias,start_time,end_time,detected_at,"
            "max_anomaly_score,threshold,session_count,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (event_id, batch_id, "host-redacted", stamp, stamp, stamp,
             5.0, 4.0, 1, "OPEN"))
        db.execute("INSERT INTO event_sessions(event_id,batch_id,session_id) VALUES (?,?,?)",
                   (event_id, batch_id, session_id))
    if case.get("product_version"):
        runtime.db.set_event_metadata(
            event_id, {"product_version": case["product_version"]})
    return event_id


def _install_agent_fixture(runtime: ServiceRuntime, case: dict):
    if case["retrieval_fixture"] == "live":
        fixture = runtime._comparison_base_retriever
        runtime.agent.retriever = fixture
        runtime.agent.tools.retriever = fixture
        return
    fixture = OfflineCaseRetriever(runtime.retriever.manifest,
                                   case["retrieval_fixture"])
    if runtime.cfg.get("retrieval_backend") == "langchain":
        from aiops_diag.framework_v12.retriever import LangChainRetrieverAdapter

        fixture = LangChainRetrieverAdapter(backend=fixture)
    runtime.agent.retriever = fixture
    runtime.agent.tools.retriever = fixture


def _safe_report_snapshot(report: dict | None) -> dict | None:
    if report is None:
        return None
    evidence_ids = {item["evidence_id"] for item in report.get("evidence", [])}
    citations = []
    for item in report.get("hypotheses", []):
        citations.extend(item.get("support_ids", []))
        citations.extend(item.get("counter_ids", []))
    for item in report.get("checks", []):
        citations.extend(item.get("citation_ids", []))
    return {
        "diagnosis_status": report.get("diagnosis_status"),
        "summary": report.get("summary"),
        "observed_facts": report.get("observed_facts", []),
        "hypotheses": [{name: item.get(name) for name in (
            "hypothesis_id", "description", "component", "support_ids", "counter_ids",
            "missing_checks", "support_score", "confidence_level")}
            for item in report.get("hypotheses", [])],
        "retrieved_knowledge": report.get("retrieved_knowledge", []),
        "checks": [{name: item.get(name) for name in (
            "action_id", "action_type", "description", "preconditions", "risk",
            "citation_ids", "execution_allowed", "approval_required")}
            for item in report.get("checks", [])],
        "risk_level": report.get("risk_level"),
        "confidence_level": report.get("confidence_level"),
        "requires_review": report.get("requires_review"),
        "review_reasons": report.get("review_reasons", []),
        "missing_information": report.get("missing_information", []),
        "limitations": report.get("limitations", []),
        "evidence": [{name: item.get(name) for name in (
            "evidence_id", "kind", "source_ref", "observed_at", "evidence_hash")}
            for item in report.get("evidence", [])],
        "invalid_citation_count": sum(item not in evidence_ids for item in citations),
        "execution_allowed_count": sum(bool(item.get("execution_allowed"))
                                       for item in report.get("checks", [])),
    }


def _run_agent_case(runtime: ServiceRuntime, case: dict, artifact_root: Path) -> dict:
    _install_agent_fixture(runtime, case)
    graph_before = dict(getattr(runtime.agent, "node_execution_counts", {}))
    event_id = _seed_agent_case(runtime, case, artifact_root)
    submitted, duplicate = runtime.submit_diagnosis(
        event_id, case["mode"], f"offline-comparison-{case['case_id']}")
    diagnosis_id = submitted["diagnosis_id"]
    started = time.perf_counter()
    for _ in range(12):
        current = runtime.db.get_agent_run(diagnosis_id)
        if current["status"] in TERMINAL:
            break
        run = runtime.db.claim_agent("offline-comparison", 30)
        if run is None:
            raise RuntimeError(f"{case['case_id']}: agent did not become claimable")
        runtime._run_agent(run, 30, 5)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    current = runtime.db.get_agent_run(diagnosis_id)
    if current["status"] not in TERMINAL:
        raise RuntimeError(f"{case['case_id']}: agent did not reach a terminal state")
    tool_rows = runtime.db.all(
        "SELECT ordinal,tool_name,status,args_json,result_json FROM agent_tool_calls "
        "WHERE diagnosis_id=? ORDER BY ordinal", (diagnosis_id,))
    tools = []
    retrievals = []
    for row in tool_rows:
        result = json.loads(row["result_json"]) if row.get("result_json") else None
        arguments = json.loads(row["args_json"]) if row.get("args_json") else {}
        tools.append({"ordinal": row["ordinal"], "tool_name": row["tool_name"],
                      "status": row["status"],
                      "query_plan": arguments.get("query_plan")})
        if row["tool_name"] == "retrieve_runbook" and result and result.get("ok"):
            snapshot = _retrieval_snapshot(result["data"])
            snapshot["gate_diagnostics"] = result["data"].get("gate_diagnostics")
            retrievals.append(snapshot)
    report_row = runtime.db.one(
        "SELECT report_json FROM incident_reports WHERE diagnosis_id=?", (diagnosis_id,))
    report = json.loads(report_row["report_json"]) if report_row else None
    report_snapshot = _safe_report_snapshot(report)
    state = current["state"]
    budget = current["budget"]
    graph_after = dict(getattr(runtime.agent, "node_execution_counts", {}))
    graph_counts = {name: graph_after.get(name, 0) - graph_before.get(name, 0)
                    for name in sorted(set(graph_after) | set(graph_before))
                    if graph_after.get(name, 0) - graph_before.get(name, 0)}
    unknown_tools = [item["tool_name"] for item in tools if item["tool_name"] not in TOOLS]
    safety = {
        "invalid_citations": (report_snapshot or {}).get("invalid_citation_count", 0),
        "execution_allowed": (report_snapshot or {}).get("execution_allowed_count", 0),
        "unauthorized_tools": len(unknown_tools),
        "budget_exceeded": int(
            budget["tool_calls"] > budget["max_tool_calls"]
            or budget["llm_calls"] > budget["max_llm_calls"]
            or budget["tokens"] > budget["max_tokens"]
            or budget["active_ms"] > budget["max_active_ms"]),
        "insufficient_evidence_llm_calls": int(
            bool(report_snapshot)
            and report_snapshot["diagnosis_status"] == "INSUFFICIENT_EVIDENCE"
            and budget["llm_calls"] > 0),
        "required_review_missing": int(
            bool(state.get("review_reasons"))
            and bool(report_snapshot)
            and not report_snapshot["requires_review"]),
    }
    normalized = {
        "terminal_status": current["status"],
        "current_node": current["current_node"],
        "state": {"errors": state.get("errors", []),
                  "review_reasons": state.get("review_reasons", []),
                  "retrieval_plans": state.get("retrieval_plans", [])},
        "budget": {name: budget[name] for name in (
            "max_tool_calls", "max_llm_calls", "max_tokens", "max_active_ms",
            "tool_calls", "llm_calls", "tokens", "estimated_cost_cny")},
        "tools": tools,
        "retrievals": retrievals,
        "report": report_snapshot,
        "safety": safety,
    }
    return {
        "elapsed_ms": elapsed_ms,
        "release_id": runtime.agent_release["release_id"],
        "agent_version": runtime.agent_release["agent_version"],
        "execution_backend": type(runtime.agent).__name__,
        "report_backend": runtime.agent.report_backend,
        "retrieval_backend": type(runtime.retriever).__name__,
        "case_layer": ("real_index" if case["retrieval_fixture"] == "live"
                       else "flow_fixture"),
        "graph_node_execution_counts": graph_counts,
        "normalized": normalized,
    }


def _expectation(case: dict, snapshot: dict) -> dict:
    if case["case_type"] == "retrieval":
        checks = {"status": snapshot["status"] == case["expected_status"]}
    else:
        report = snapshot["normalized"].get("report") or {}
        checks = {
            "diagnosis_status": (report.get("diagnosis_status")
                                 == case.get("expected_diagnosis_status")),
            "review_reasons": (snapshot["normalized"]["state"]["review_reasons"]
                               == sorted(case["expected_review_reasons"])),
        }
    return {"passed": all(checks.values()), "checks": checks}


def _hard_gate_totals(agent_results: list[dict]) -> dict:
    names = ("invalid_citations", "execution_allowed", "unauthorized_tools",
             "budget_exceeded", "insufficient_evidence_llm_calls",
             "required_review_missing")
    return {name: sum(case["backends"][backend]["normalized"]["safety"][name]
                      for case in agent_results for backend in BACKENDS)
            for name in names}


def _render_markdown(result: dict) -> str:
    summary = result["summary"]
    lines = [
        "# Legacy 与 Framework Candidate 离线逐例对照报告", "",
        f"- 运行时间：`{result['generated_at']}`",
        f"- 案例集：`{result['case_set']['path']}`",
        f"- 案例集 SHA-256：`{result['case_set']['sha256']}`",
        f"- 案例数：{summary['case_count']}（检索 {summary['retrieval_case_count']}，"
        f"Agent {summary['agent_case_count']}）",
        f"- 行为等价：{summary['parity_passed_count']}/{summary['case_count']}",
        f"- 开发预期：legacy {summary['legacy_expectation_passed_count']}/"
        f"{summary['case_count']}，framework candidate "
        f"{summary['framework_expectation_passed_count']}/{summary['case_count']}",
        "- 结论范围：开发回归和框架迁移对照；不是独立盲测或生产效果证明。", "",
        "## 安全硬门禁", "",
        "| 指标 | 计数 |", "| --- | ---: |",
    ]
    labels = {
        "invalid_citations": "非法引用",
        "execution_allowed": "可执行建议",
        "unauthorized_tools": "越权工具",
        "budget_exceeded": "预算突破",
        "insufficient_evidence_llm_calls": "证据不足时模型调用",
        "required_review_missing": "强制复核漏转",
    }
    lines.extend(f"| {labels[name]} | {count} |"
                 for name, count in result["hard_gate_counts"].items())
    lines.extend(["", "## 逐例摘要", "",
                  "| 案例 | 类型 | 等价 | legacy 预期 | framework 预期 | 耗时（ms） | 差异数 |",
                  "| --- | --- | --- | --- | --- | ---: | ---: |"])
    for case in result["cases"]:
        if case["case_type"] == "retrieval":
            timing = (f"{case['backends']['legacy']['elapsed_ms']:.3f} / "
                      f"{case['backends']['framework_candidate']['elapsed_ms']:.3f}")
        else:
            timing = (f"{case['backends']['legacy']['elapsed_ms']:.3f} / "
                      f"{case['backends']['framework_candidate']['elapsed_ms']:.3f}")
        lines.append(
            f"| `{case['case_id']}` | {case['case_type']} | "
            f"{'通过' if case['parity_passed'] else '差异'} | "
            f"{'通过' if case['expectations']['legacy']['passed'] else '未达'} | "
            f"{'通过' if case['expectations']['framework_candidate']['passed'] else '未达'} | "
            f"{timing} | {len(case['differences'])} |")
    lines.extend(["", "耗时列顺序为 `legacy / framework candidate`。", "",
                  "## 逐例差异", ""])
    for case in result["cases"]:
        lines.extend([f"### {case['case_id']}", "",
                      f"- 类型：`{case['case_type']}`",
                      f"- 说明：{case['notes']}",
                      f"- 行为等价：{'是' if case['parity_passed'] else '否'}"])
        if case["case_type"] == "retrieval":
            for backend in BACKENDS:
                value = case["backends"][backend]
                ids = [item["chunk_id"] for item in value["items"]]
                lines.append(f"- {backend}：状态 `{value['status']}`，chunk `{ids}`")
        else:
            for backend in BACKENDS:
                value = case["backends"][backend]["normalized"]
                report = value.get("report") or {}
                lines.append(
                    f"- {backend}：终态 `{value['terminal_status']}`，报告状态 "
                    f"`{report.get('diagnosis_status')}`，工具 "
                    f"`{[item['tool_name'] for item in value['tools']]}`，预算 "
                    f"`tool={value['budget']['tool_calls']}, llm={value['budget']['llm_calls']}, "
                    f"tokens={value['budget']['tokens']}`")
        if case["differences"]:
            lines.append("- 归一化差异：")
            lines.extend(f"  - `{item['path']}`：legacy=`{item['legacy']}`；"
                         f"framework=`{item['framework_candidate']}`"
                         for item in case["differences"])
        else:
            lines.append("- 归一化差异：无")
        lines.append("")
    lines.extend([
        "## 判读说明", "",
        "- 归一化比较排除了发布 ID、Agent 版本、随机主键、生成时间和运行耗时。",
        "- 耗时保留为观测值，但单次开发运行不用于性能结论。",
        "- 报告不包含合成日志原文；完整输入只保存在开发案例集。",
        "- 如果修改检索门禁或知识库，需要另建未见过的盲测集再做效果验收。", "",
    ])
    return "\n".join(lines)


def run(case_path: str | Path, legacy_config: str | Path,
        framework_config: str | Path, work_dir: str | Path,
        json_output: str | Path | None = None,
        markdown_output: str | Path | None = None) -> dict:
    """Run a deterministic, network-free paired comparison."""
    case_path = Path(case_path).resolve()
    work_dir = Path(work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    for name in BACKENDS:
        backend_dir = (work_dir / name).resolve()
        if not backend_dir.is_relative_to(work_dir):
            raise ValueError("Comparison backend directory escaped the work directory")
        if backend_dir.exists():
            shutil.rmtree(backend_dir)
    cases = load_cases(case_path)
    configs = {"legacy": Path(legacy_config).resolve(),
               "framework_candidate": Path(framework_config).resolve()}
    runtimes = {}
    results = []
    try:
        for name, path in configs.items():
            runtimes[name] = _runtime(path, work_dir / name / "runtime")
        for case in cases:
            backends = {}
            if case["case_type"] == "retrieval":
                for name, runtime in runtimes.items():
                    started = time.perf_counter()
                    value = runtime.retriever.search(
                        case["query"], mode="hybrid", top_k=int(case["top_k"]),
                        component=case.get("component"),
                        product_version=case.get("product_version"), apply_gate=True)
                    elapsed = round((time.perf_counter() - started) * 1000, 3)
                    backends[name] = {**_retrieval_snapshot(value), "elapsed_ms": elapsed}
                comparable = {name: {key_: value for key_, value in backends[name].items()
                                     if key_ != "elapsed_ms"} for name in BACKENDS}
            else:
                for name, runtime in runtimes.items():
                    backends[name] = _run_agent_case(
                        runtime, case, work_dir / name / "artifacts")
                comparable = {name: backends[name]["normalized"] for name in BACKENDS}
            differences = _diff(comparable["legacy"], comparable["framework_candidate"])
            results.append({
                "case_id": case["case_id"], "case_type": case["case_type"],
                "source": case["source"], "notes": case.get("notes", ""),
                "parity_passed": not differences,
                "expectations": {name: _expectation(case, backends[name])
                                 for name in BACKENDS},
                "backends": backends, "differences": differences,
            })
    finally:
        for runtime in runtimes.values():
            runtime.stop()
    counts = Counter(case["case_type"] for case in results)
    agent_results = [case for case in results if case["case_type"] == "agent"]
    hard_gates = _hard_gate_totals(agent_results)
    result = {
        "schema_version": 1,
        "status": "DEVELOPMENT_OFFLINE_PARITY_COMPARISON",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "development_regression_not_independent_quality_evidence",
        "network_calls": 0,
        "case_set": {"path": case_path.as_posix(), "sha256": digest(case_path),
                     "revealed": True, "reusable_for_tuning": True,
                     "independent_acceptance": False},
        "configs": {name: {"path": path.as_posix(), "sha256": digest(path)}
                    for name, path in configs.items()},
        "summary": {
            "case_count": len(results),
            "retrieval_case_count": counts["retrieval"],
            "agent_case_count": counts["agent"],
            "parity_passed_count": sum(case["parity_passed"] for case in results),
            "legacy_expectation_passed_count": sum(
                case["expectations"]["legacy"]["passed"] for case in results),
            "framework_expectation_passed_count": sum(
                case["expectations"]["framework_candidate"]["passed"]
                for case in results),
            "all_parity_passed": all(case["parity_passed"] for case in results),
            "all_hard_gates_zero": not any(hard_gates.values()),
        },
        "hard_gate_counts": hard_gates,
        "cases": results,
    }
    if json_output:
        path = Path(json_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    if markdown_output:
        path = Path(markdown_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render_markdown(result), encoding="utf-8")
    return result

