"""模块说明：把实验证据日志接入诊断链路，跑 Agent 并回填映射。"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# 变量说明：ROOT 指向仓库根目录。
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from aiops_diag.data.common import digest, key
from aiops_diag.diagnosis.engine import AgentEngine, AgentYield
from aiops_diag.platform.db import Database
from aiops_diag.platform.pipeline import LOG_SCHEMA

# 变量说明：LINE 解析容器日志的通用前缀。
LINE = re.compile(r"^\[(?P<host>[^\]]+)\]\s+(?P<stamp>\d{4}-\d{2}-\d{2} "
                  r"\d{2}:\d{2}:\d{2})(?:[.,]\d+)?\s+(?P<level>[A-Z]+)\s+(?P<rest>.*)$")
# 变量说明：CARDS 是知识卡目录。
CARDS = ROOT / "resources" / "knowledge" / "cards"


# 类说明：CardRetriever 用知识卡做确定性检索，供实验室接入使用。
class CardRetriever:
    # 方法说明：__init__ 载入知识卡并给出稳定的知识库标识。
    def __init__(self, directory=CARDS):
        self.cards = []
        for path in sorted(Path(directory).glob("*.json")):
            card = json.loads(path.read_text(encoding="utf-8"))
            text = " ".join(section.get("text", "") for section in card.get("sections", []))
            codes = card.get("root_cause_codes") or []
            self.cards.append({"chunk_id": f"kb_{card['doc_id']}", "doc_id": card["doc_id"],
                               "title": card.get("title", ""), "text": text,
                               "component": card.get("component") or [],
                               "root_cause_code": codes[0] if codes else None,
                               "root_cause_codes": codes,
                               "section_path": card.get("category", "hdfs"),
                               "source_url": None})
        self.manifest = {"kb_release_id": "kb_lab_cards"}

    # 方法说明：search 按关键词重叠返回 Top-K 知识卡。
    def search(self, query, mode=None, top_k=3, component=None, product_version=None,
               apply_gate=True, code=None):
        tokens = set(re.findall(r"[a-z0-9]+", (query or "").lower()))
        pool = self.cards
        if code:
            narrowed = [card for card in self.cards if card.get("root_cause_code") == code]
            if narrowed:
                pool = narrowed
        if component:
            matched = [card for card in pool if component.lower() in
                       [str(item).lower() for item in card["component"]]]
            if matched:
                pool = matched
        signals = {"DN_VOLUME": ("no space left", "volume failed", "failed volume",
                                 "disk full"),
                   "NN_AVAILABILITY": ("connection refused", "failed to connect",
                                       "retrying connect"),
                   "DN_HEARTBEAT": ("lost heartbeat", "lost datanode",
                                    "dead datanode", "removedead"),
                   "NN_SAFE_MODE": ("safe mode",)}
        lowered = (query or "").lower()
        codes = [code for code, words in signals.items()
                 if code.lower() in lowered
                 or any(word in lowered for word in words)]
        if codes:
            narrowed = [card for card in pool if card.get("root_cause_code") in codes]
            if narrowed:
                pool = narrowed
        synonyms = {"heartbeat": ("心跳",), "dead": ("心跳", "失效"),
                    "volume": ("卷", "磁盘"), "space": ("空间",), "disk": ("磁盘",)}
        phrases = {"safe mode": 6, "no space left": 6, "volume failed": 4,
                   "lost heartbeat": 6, "dead datanode": 4}
        pairs = re.findall(r"[a-z]+ [a-z]+", (query or "").lower())
        scored = []
        for order, card in enumerate(pool):
            body = card["text"].lower()
            title = card["title"].lower()
            hits = sum(1 for token in tokens if token and token in body)
            hits += 2 * sum(1 for token in tokens if token and token in title)
            hits += 2 * sum(1 for pair in pairs if pair in body)
            hits += sum(1 for token in tokens for word in synonyms.get(token, ())
                        if word in card["text"])
            hits += sum(weight for phrase, weight in phrases.items() if phrase in body)
            if component and component.lower() in [str(item).lower()
                                                   for item in card["component"]]:
                hits += 5
            scored.append((hits, order, card))
        scored.sort(key=lambda item: (-item[0], item[1]))
        items = []
        for rank, (hits, _, card) in enumerate(scored[: int(top_k)], 1):
            items.append({**card, "rank": rank, "bm25_score": float(hits),
                          "dense_score": None, "rrf_score": 1.0 / (60 + rank)})
        return {"status": "evidence_found" if items else "insufficient_evidence",
                "mode": "lab", "items": items, "gate_score": 1.0 if items else None}


# 类说明：FrozenCodeRetriever 在冻结检索器上补一层根因码过滤。
class FrozenCodeRetriever:
    # 方法说明：__init__ 保存底层冻结检索器。
    def __init__(self, inner):
        self.inner = inner
        self.manifest = inner.manifest

    # 方法说明：search 在需要时扩大召回并按根因码过滤。
    def search(self, query, mode=None, top_k=3, component=None, product_version=None,
               apply_gate=True, code=None):
        result = self.inner.search(query, mode=mode, top_k=10,
                                   component=component,
                                   product_version=product_version, apply_gate=False)
        items = result.get("items", [])
        if code:
            code_chunks = [chunk for chunk in getattr(self.inner.engine, "chunks", [])
                           if chunk.get("root_cause_code") == code]
            items = code_chunks[:int(top_k)] + items
        seen, unique = set(), []
        for item in items:
            doc = item.get("doc_id") or item.get("chunk_id")
            if doc in seen:
                continue
            seen.add(doc)
            unique.append(item)
        return {**result, "items": unique[:int(top_k)]}

    # 方法说明：__getattr__ 透传 chunk 等方法。
    def __getattr__(self, name):
        return getattr(self.inner, name)


# 类说明：OfflineClient 表示实验室接入不调用付费模型。
class OfflineClient:
    # 变量说明：configured 表示未配置模型。
    configured = False

    # 方法说明：close 保持与真实客户端一致的接口。
    def close(self):
        return None


# 方法说明：_parse 把容器日志转换为平台日志行。
def _parse(text, session_id, fallback=None):
    rows, total = [], 0
    for line in text.splitlines():
        total += 1
        if not line.strip():
            continue
        match = LINE.match(line)
        if match:
            host = match.group("host")
            stamp = match.group("stamp").replace(" ", "T") + "+00:00"
            level = match.group("level")
            rest = match.group("rest")
            component, _, message = rest.partition(":")
        else:
            prefix = re.match(r"^\[([^\]]+)\]\s*(.*)$", line)
            host = prefix.group(1) if prefix else "lab"
            content = prefix.group(2) if prefix else line
            stamp = fallback
            level = "ERROR" if ("Exception" in content or "ERROR" in content) else "INFO"
            component, message = "lab", content
        if "namenode" in host:
            component = "NameNode"
        elif "dn" in host or "datanode" in host:
            component = "DataNode"
        rows.append({"log_id": "log_" + key([session_id, total])[:20],
                     "raw_line_no": total, "timestamp": stamp, "level": level,
                     "component": component, "redacted_message": message.strip(),
                     "template_id": 2 if level in ("ERROR", "WARN") else 1,
                     "session_ids": [session_id], "parse_status": "ok"})
    return rows, total


# 方法说明：ingest 把一条实验日志接入平台并跑一次模板诊断。
def ingest_log(case_id, log_path, database_path, start, end, mode="template",
               focus_component=None, agent_backend="native", retriever_kind="cards",
               retriever=None):
    log_path = Path(log_path)
    text = log_path.read_text(encoding="utf-8")
    tag = uuid.uuid4().hex[:6]
    session_id = "ses_" + key([case_id, tag])[:20]
    rows, total = _parse(text, session_id, start)

    database = Database(database_path)
    database.init()
    work = Path(database_path).parent / "lab_work"
    work.mkdir(parents=True, exist_ok=True)
    release_dir = work / "release"
    release_dir.mkdir(exist_ok=True)
    (release_dir / "service_release.json").write_text(json.dumps({"release_id": "lab_rule_lr"}),
                                                      encoding="utf-8")

    source = work / f"{case_id}.log"
    source.write_text(text, encoding="utf-8")
    input_hash = key([digest(source), tag])
    batch_id = "bat_" + key([input_hash, "lab"])[:24]
    task_id = "tsk_" + key([input_hash, "lab"])[:24]
    database.create_task(batch_id, task_id, "upload", str(source), input_hash,
                         "lab_rule_lr", "lab", key([input_hash, "lab"]))
    task = database.claim("lab-worker", 60)
    directory = work / "batches" / batch_id
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for name in ("logs.parquet", "quarantine.parquet", "links.parquet", "sessions.parquet",
                 "predictions.parquet", "events.parquet", "event_sessions.parquet"):
        path = directory / name
        if name == "logs.parquet":
            pq.write_table(pa.Table.from_pylist(rows, schema=LOG_SCHEMA), path)
        else:
            path.write_text("", encoding="utf-8")
        artifacts[name] = {"relative_path": name, "sha256": digest(path)}

    detected = datetime.now(timezone.utc).isoformat()
    event_id = "evt_" + key([case_id, tag])[:24]
    counts = {"total_lines": total, "parsed_lines": len(rows),
              "quarantined_lines": total - len(rows), "session_count": 1,
              "anomaly_count": 1, "event_count": 1}
    database.complete(task_id, directory, counts,
                      [{"session_id": session_id, "start_time": start, "end_time": end,
                        "line_count": len(rows), "unknown_count": 0, "anomaly_score": 2.0,
                        "threshold": 1.0, "prediction": 1,
                        "first_log_id": rows[0]["log_id"], "last_log_id": rows[-1]["log_id"],
                        "host_alias": focus_component or "lab"}],
                      [{"event_id": event_id, "batch_id": batch_id,
                        "host_alias": focus_component or "lab",
                        "start_time": start, "end_time": end, "detected_at": detected,
                        "max_anomaly_score": 2.0, "threshold": 1.0, "session_count": 1,
                        "status": "ANOMALY_DETECTED"}],
                      [{"event_id": event_id, "session_id": session_id}],
                      artifacts, task["lease_token"])

    cfg = {"agent_version": "lab_agent", "v12": {"enabled": False},
           "workflow": {"max_tool_calls": 8, "max_llm_calls": 3, "max_tokens": 12000,
                        "max_active_seconds": 120, "optional_router_enabled": False,
                        "context_strategy": "full"},
           "tools": {"query_logs_limit": 50, "similar_incidents_limit": 3,
                     "runbook_top_k": 5},
           "approval": {"ttl_hours": 24},
           "rag": {"provider": {"name": "deepseek"}, "budget": {}, "paths": {}}}
    release = {"schema_version": 1, "agent_version": "lab_agent", "release_id": "agr_lab",
               "rag_version": "lab", "kb_release_id": "kb_lab_cards",
               "tool_manifest_hash": "lab", "risk_policy_hash": "lab",
               "prompt_version": "lab"}
    detector = {"release_id": "lab_rule_lr", "model_id": "lab_rule_detector",
                "threshold": 1.0}
    if retriever is None:
        if retriever_kind == "frozen":
            from aiops_diag.knowledge.config import load as load_knowledge
            from aiops_diag.knowledge.release import FrozenRetriever
            retriever = FrozenCodeRetriever(
                FrozenRetriever(load_knowledge(
                    ROOT / "resources" / "configs" / "retrieval.yaml")))
        else:
            retriever = CardRetriever()
    if agent_backend == "langgraph":
        from aiops_diag.diagnosis.framework.graph import LangGraphAgentEngine
        cfg.update({
            "v12": {"enabled": True},
            "execution_backend": "langgraph",
            "tools": {**cfg["tools"], "query_logs_limit": 1000},
            "report_backend": "legacy",
            "query_builder": dict(
                yaml.safe_load((ROOT / "resources" / "configs" / "query_builder_v1.yaml")
                               .read_text(encoding="utf-8")),
                config_sha256=digest(ROOT / "resources" / "configs" / "query_builder_v1.yaml")),
        })
        engine = LangGraphAgentEngine(cfg, database, retriever, detector,
                                      release, client=OfflineClient())
    else:
        engine = AgentEngine(cfg, database, retriever, detector, release,
                             client=OfflineClient())
    fingerprint = key([event_id, mode, "agr_lab"])
    diagnosis_id = "dia_" + fingerprint[:24]
    budget = {"max_tool_calls": 8, "max_llm_calls": 3, "max_tokens": 12000,
              "max_active_ms": 120000, "tool_calls": 0, "llm_calls": 0, "tokens": 0,
              "active_ms": 0, "estimated_cost_cny": 0.0}
    database.create_agent_run(diagnosis_id, event_id, mode, "agr_lab", fingerprint,
                              budget, None, 16)
    for _ in range(16):
        run = database.claim_agent("lab-worker", 30)
        if run is None:
            break
        try:
            engine.run(run)
        except AgentYield as yielded:
            database.yield_agent(run["diagnosis_id"], run["lease_token"], str(yielded))
            continue
        break
    engine.close()
    row = database.one("SELECT report_id FROM agent_runs WHERE diagnosis_id=?", (diagnosis_id,))
    report = database.one("SELECT report_id FROM incident_reports WHERE diagnosis_id=?",
                          (diagnosis_id,))
    mapping = {"incident_id": case_id, "batch_id": batch_id, "event_id": event_id,
               "diagnosis_id": diagnosis_id, "report_id": report["report_id"] if report else None,
               "agent_detected": detected, "mode": "lab-ingest"}
    return mapping


# 方法说明：ingest 读取已生成的案例并调用 ingest_log，回填 map.json。
def ingest(case_dir, database_path, mode="template", agent_backend="native",
           retriever_kind="cards", retriever=None):
    case_dir = Path(case_dir)
    incident = json.loads((case_dir / "incident.json").read_text(encoding="utf-8"))
    logs_path = next((case_dir / "evidence" / "logs").glob("*.log"))
    code = incident["labels"]["root_cause_code"]
    focus = "NameNode" if code.startswith("NN_") else "DataNode"
    mapping = ingest_log(incident["incident_id"], logs_path, database_path,
                         incident["timestamps"]["fault_start"],
                         incident["timestamps"]["first_observable_signal"], mode,
                         focus_component=focus, agent_backend=agent_backend,
                         retriever_kind=retriever_kind, retriever=retriever)
    (case_dir / "map.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2)
                                       + "\n", encoding="utf-8")
    return mapping


# 方法说明：main 接入一条实验案例并打印映射。
def main(argv=None):
    parser = argparse.ArgumentParser(description="Ingest a lab case into the diagnosis chain")
    parser.add_argument("--case", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--agent-backend", choices=("native", "langgraph"),
                        default="native")
    parser.add_argument("--retriever", choices=("cards", "frozen"), default="cards")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(ingest(args.case, args.database,
                            agent_backend=args.agent_backend,
                            retriever_kind=args.retriever),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
