"""离线演示：一条 HDFS 日志走完 解析 → 事件 → 诊断 → 人工复核 的完整链路。

演示不调用任何付费模型：检测器是确定性的规则版本，知识检索使用本地知识卡。
目的是让面试官或新同学在 5 分钟内看到系统真实产出，而不是只看截图。

运行方式：
    python demo/run_demo.py            # 交互式文本输出
    python demo/run_demo.py --json     # 机器可读摘要（用于 CI 冒烟）
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiops_diag.data.common import digest, key
from aiops_diag.diagnosis.engine import AgentEngine, AgentYield
from aiops_diag.platform.db import Database
from aiops_diag.platform.pipeline import database_payload, process

DEMO_RELEASE_ID = "demo_rule_lr"
AGENT_RELEASE_ID = "agr_demo"
KB_RELEASE_ID = "kb_demo_v1"
WORKER_ID = "demo-worker"


# 类说明：DemoDetector 是演示用的确定性检测器，替代训练好的 TF-IDF+LR 模型。
class DemoDetector:
    """只做一件事：包含 ERROR/FATAL 的会话判为异常。

    真实系统里这一步由冻结的 Drain3 模板 + TF-IDF + 逻辑回归完成，
    这里用规则替代，是为了让演示不依赖训练制品，同时保持接口一致。
    """

    manifest = {"release_id": DEMO_RELEASE_ID}
    threshold = 1.0

    # 方法说明：template 把日志行映射为模板编号，ERROR/FATAL 记为 2。
    def template(self, row):
        level = (row.get("level") or "").upper()
        return 2 if level in ("ERROR", "FATAL") else 1

    # 方法说明：score 给每个会话打分，返回分数与是否超过阈值。
    def score(self, sequences):
        scores = np.asarray([2.0 if 2 in row else -2.0 for row in sequences],
                            dtype=np.float64)
        return scores, (scores >= self.threshold).astype(np.int8)

    # 方法说明：assert_unchanged 真实模型会校验制品未被篡改，演示版为空实现。
    def assert_unchanged(self):
        return None

    # 方法说明：public 返回可写入发布清单的模型元数据。
    def public(self):
        return {
            "schema_version": 1,
            "release_id": DEMO_RELEASE_ID,
            "model_id": "demo_rule_detector",
            "model_family": "rule_based",
            "threshold": self.threshold,
            "anomaly_score_semantics": "larger_is_more_anomalous_uncalibrated",
            "protocol_hash": "demo",
            "template_manifest_hash": "demo",
        }


# 方法说明：_tokens 把文本切分为小写词元，供演示检索器打分。
def _tokens(text):
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


# 类说明：DemoRetriever 是按关键词打分的本地知识检索器，替代 BM25+BGE 混合检索。
class DemoRetriever:
    """演示用检索器：关键词命中优先，未命中时按固定顺序补齐。

    真实系统里由 BM25 与 BGE 向量各自召回 20 条、再用 RRF 融合，
    并对无答案场景做证据门禁。
    """

    # 方法说明：__init__ 读取知识卡并记录发布标识。
    def __init__(self, cards):
        self.cards = list(cards)
        self.manifest = {"kb_release_id": KB_RELEASE_ID}

    # 方法说明：search 返回排序后的知识条目，字段与真实检索器保持一致。
    def search(self, query, mode=None, top_k=3, component=None,
               product_version=None, apply_gate=True):
        tokens = _tokens(query)
        scored = []
        for order, card in enumerate(self.cards):
            terms = _tokens(" ".join(card.get("match_terms", [])))
            hits = len(tokens & terms)
            scored.append((hits, order, card))
        scored.sort(key=lambda item: (-item[0], item[1]))
        chosen = scored[: int(top_k)]
        items = []
        for rank, (hits, _, card) in enumerate(chosen, 1):
            items.append({
                "chunk_id": card["chunk_id"],
                "doc_id": card["doc_id"],
                "title": card["title"],
                "section_path": card["section_path"],
                "component": card["components"],
                "version_scope": card["version_scope"],
                "source_url": card["source_url"],
                "text": card["text"],
                "rank": rank,
                "bm25_score": float(hits),
                "dense_score": None,
                "rrf_score": 1.0 / (60 + rank),
            })
        return {"status": "evidence_found", "mode": "demo", "items": items,
                "gate_score": 1.0}


# 类说明：OfflineClient 表示没有配置大模型，让 Agent 走确定性模板降级。
class OfflineClient:
    configured = False

    # 方法说明：close 保持与真实客户端一致的资源释放接口。
    def close(self):
        return None


# 方法说明：_rule 打印分节标题，让终端输出更像一次演示。
def _rule(title):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


# 方法说明：main 串起解析、检测、诊断、复核，并输出演示报告。
def main(argv=None):
    parser = argparse.ArgumentParser(description="AIOps offline demo")
    parser.add_argument("--workdir", default=str(ROOT / "demo" / ".runtime"))
    parser.add_argument("--json", action="store_true", help="只输出机器可读摘要")
    parser.add_argument("--keep", action="store_true", help="保留运行目录便于检查")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    real_stdout = sys.stdout
    if args.json:
        sys.stdout = io.StringIO()

    started = time.perf_counter()
    work = Path(args.workdir).resolve()
    if work.exists():
        shutil.rmtree(work)
    (work / "release").mkdir(parents=True)
    (work / "runtime").mkdir(parents=True)
    (work / "release" / "service_release.json").write_text(
        json.dumps({"release_id": DEMO_RELEASE_ID, "note": "demo"}, ensure_ascii=False),
        encoding="utf-8")

    cfg = {
        "paths": {"runtime_dir": str(work / "runtime")},
        "release_dir": str(work / "release"),
        "processing_hash": "demo",
        "processing": {
            "max_line_bytes": 1024 * 1024,
            "parquet_batch_rows": 100,
            "inference_batch_sessions": 10,
            "event_max_gap_seconds": 300,
            "event_max_span_seconds": 1800,
        },
    }

    cards = [json.loads(path.read_text(encoding="utf-8"))
             for path in sorted((ROOT / "demo" / "fixtures" / "knowledge").glob("*.json"))]
    detector = DemoDetector()
    retriever = DemoRetriever(cards)
    db = Database(work / "service.sqlite3")
    db.init()

    source = work / "input.log"
    source.write_bytes((ROOT / "demo" / "fixtures" / "hdfs_demo.log").read_bytes())
    input_hash = digest(source)
    batch_id = "bat_" + input_hash[:24]
    task_id = "tsk_" + input_hash[:24]

    _rule("AIOps 故障诊断 Agent · 离线演示（不调用大模型）")
    print(f"工作目录: {work}")
    print("输入日志: demo/fixtures/hdfs_demo.log")

    db.create_task(batch_id, task_id, "upload", str(source), input_hash,
                   DEMO_RELEASE_ID, "demo", key([input_hash, DEMO_RELEASE_ID, "demo"]))
    task = db.claim(WORKER_ID, 30)
    directory, manifest = process(task, cfg, detector, lambda stage: None)
    counts, sessions, events, members, artifacts = database_payload(directory, manifest)
    db.complete(task_id, directory, counts, sessions, events, members, artifacts,
                task["lease_token"])

    _rule("[1/7] 解析、脱敏与异常检测")
    print(f"  总行数 {counts['total_lines']} | 解析成功 {counts['parsed_lines']} | "
          f"隔离 {counts['quarantined_lines']} | 会话 {counts['session_count']} | "
          f"异常会话 {counts['anomaly_count']} | 事件 {counts['event_count']}")
    print("  说明：解析失败或没有 block 编号的行进入隔离区，不会被静默丢弃。")

    event = db.one("SELECT * FROM events WHERE batch_id=?", (batch_id,))
    _rule("[2/7] 事件聚合")
    print(f"  {event['event_id']} | 主机 {event['host_alias']} | "
          f"会话数 {event['session_count']} | 最高分 {event['max_anomaly_score']:.2f} "
          f"(阈值 {event['threshold']:.2f}) | 时间窗 {event['start_time']} ~ {event['end_time']}")

    agent_cfg = {
        "agent_version": "demo_agent_v1",
        "workflow": {"max_tool_calls": 8, "max_llm_calls": 3, "max_tokens": 12000,
                     "max_active_seconds": 120, "optional_router_enabled": False},
        "tools": {"query_logs_limit": 50, "similar_incidents_limit": 3,
                  "runbook_top_k": 3},
        "approval": {"ttl_hours": 24},
        "v12": {"enabled": False},
        "rag": {"provider": {"name": "deepseek"}, "budget": {}, "paths": {}},
    }
    agent_release = {
        "schema_version": 1, "agent_version": "demo_agent_v1",
        "release_id": AGENT_RELEASE_ID, "rag_version": "demo",
        "kb_release_id": KB_RELEASE_ID, "tool_manifest_hash": "demo",
        "risk_policy_hash": "demo", "prompt_version": "demo_prompt_v1",
    }
    service_manifest = {"release_id": DEMO_RELEASE_ID,
                        "model_id": "demo_rule_detector", "threshold": detector.threshold}
    engine = AgentEngine(agent_cfg, db, retriever, service_manifest, agent_release,
                         client=OfflineClient())

    fingerprint = key([event["event_id"], "template", AGENT_RELEASE_ID])
    diagnosis_id = "dia_" + fingerprint[:24]
    budget = {"max_tool_calls": 8, "max_llm_calls": 3, "max_tokens": 12000,
              "max_active_ms": 120000, "tool_calls": 0, "llm_calls": 0, "tokens": 0,
              "active_ms": 0, "estimated_cost_cny": 0.0}
    db.create_agent_run(diagnosis_id, event["event_id"], "template", AGENT_RELEASE_ID,
                        fingerprint, budget, None, 16)

    _rule("[3/7] 受控诊断：每个节点完成后主动让出 worker")
    for _ in range(16):
        run = db.claim_agent(WORKER_ID, 30)
        if run is None:
            break
        try:
            engine.run(run)
        except AgentYield as yielded:
            db.yield_agent(run["diagnosis_id"], run["lease_token"], str(yielded))
            print(f"  节点完成 -> {yielded}")
            continue
        break

    final_run = db.get_agent_run(diagnosis_id)
    report_row = db.one("SELECT * FROM incident_reports WHERE diagnosis_id=?",
                        (diagnosis_id,))
    if report_row is None:
        raise SystemExit(f"演示失败：未生成报告（run 状态 {final_run['status']}）")
    report = json.loads(report_row["report_json"])

    tool_rows = db.all("SELECT tool_name,status FROM agent_tool_calls "
                       "WHERE diagnosis_id=? ORDER BY ordinal", (diagnosis_id,))
    kinds = {}
    for item in report["evidence"]:
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    _rule("[4/7] 证据与候选原因")
    names = {}
    for row in tool_rows:
        names[row["tool_name"]] = names.get(row["tool_name"], 0) + 1
    shown = ", ".join(names.keys())
    print(f"  工具调用 {len(tool_rows)} 次 / {len(names)} 类：{shown}")
    print(f"  证据 {len(report['evidence'])} 条（日志 {kinds.get('log', 0)} / "
          f"知识 {kinds.get('doc', 0)}）")
    for item in report["hypotheses"]:
        print(f"  - {item['hypothesis_id']}: {item['description']} "
              f"(support={len(item['support_ids'])}, confidence={item['confidence_level']})")
    print(f"  状态 {report['diagnosis_status']} | 置信度 {report['confidence_level']} | "
          f"需复核 {report['requires_review']} {report['review_reasons']}")
    if report["diagnosis_status"] == "DEGRADED_TEMPLATE":
        print("  说明：离线演示没有配置 API Key，因此按设计降级为确定性模板；"
              "配置 DeepSeek 后会走证据约束的大模型报告。")

    allowed = {item["evidence_id"] for item in report["evidence"]}
    cited = set()
    for item in report["hypotheses"]:
        cited.update(item["support_ids"])
        cited.update(item["counter_ids"])
    for item in report["checks"]:
        cited.update(item["citation_ids"])
    illegal = sorted(cited - allowed)
    unsafe = [item for item in report["checks"] if item["execution_allowed"]]

    _rule("[5/7] 安全门禁")
    verdict = "通过" if not illegal else "失败"
    print(f"  引用合法（全部命中本次证据）: {verdict}")
    verdict = "通过" if not unsafe else "失败"
    print(f"  所有建议 execution_allowed=false: {verdict}")
    print("  证据不足时是否调用模型: 未调用（离线模板降级）")

    _rule("[6/7] 报告正文")
    print(report_row["report_markdown"])

    approval = db.one("SELECT * FROM approvals WHERE diagnosis_id=?", (diagnosis_id,))
    _rule("[7/7] 人工复核（签字 ≠ 执行）")
    if approval is None:
        print("  本次报告未触发强制复核。")
        approval_status = "NOT_REQUIRED"
    else:
        print(f"  审批单 {approval['approval_id']} | 状态 {approval['status']} | "
              f"绑定报告哈希 {approval['report_hash'][:16]}... | 到期 {approval['expires_at']}")
        db.decide_approval(approval["approval_id"], "approve", approval["report_hash"],
                           approval["revision"], "离线演示：人工确认已阅，不执行任何操作",
                           "demo-reviewer", "demo-approval-1")
        approval_status = db.one("SELECT status FROM approvals WHERE approval_id=?",
                                 (approval["approval_id"],))["status"]
        print(f"  复核已提交：{approval_status}；系统内没有任何执行入口，"
              "批准仅代表“人看过”。")

    final_run = db.get_agent_run(diagnosis_id)
    audits = db.all("SELECT action,actor_type,created_at FROM agent_audit_records "
                    "WHERE diagnosis_id=? ORDER BY audit_id", (diagnosis_id,))
    print()
    print("  审计轨迹：")
    for row in audits[-8:]:
        print(f"    {row['created_at']}  {row['actor_type']:<8} {row['action']}")

    used = final_run["budget"]
    elapsed = time.perf_counter() - started
    summary = {
        "demo": "offline",
        "counts": counts,
        "event_id": event["event_id"],
        "diagnosis_id": diagnosis_id,
        "report_id": report["report_id"],
        "diagnosis_status": report["diagnosis_status"],
        "confidence_level": report["confidence_level"],
        "requires_review": report["requires_review"],
        "review_reasons": report["review_reasons"],
        "tool_calls": len(tool_rows),
        "evidence": len(report["evidence"]),
        "illegal_citations": len(illegal),
        "executable_advice": len(unsafe),
        "approval_status": approval_status,
        "final_status": final_run["status"],
        "llm_calls": used["llm_calls"],
        "estimated_cost_cny": used["estimated_cost_cny"],
        "elapsed_seconds": round(elapsed, 3),
    }
    if args.json:
        sys.stdout = real_stdout
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    print()
    print(f"耗时 {elapsed:.2f}s | 付费模型调用 {summary['llm_calls']} 次 | "
          f"费用 ¥{summary['estimated_cost_cny']:.4f} | 最终状态 {final_run['status']}")
    print("（本次运行的临时数据保留在 demo/.runtime，可直接查看 SQLite 与 Parquet）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
