"""模块说明：定义只读工具白名单、调用审计和结果契约。"""

import json
import time
from pathlib import Path

import pyarrow.parquet as pq

from aiops_diag.common import key
from online.knowledge.engine import tokenize
from aiops_diag.platform.metrics_store import MetricsStore


# 方法说明：`result` 完成当前步骤的业务处理；参数为 `data`、`error`、`provenance`、`started`、`truncated`。
def result(data=None, error=None, provenance=None, started=None, truncated=False):
    return {"ok": error is None, "data": data or {}, "error": error,
            "provenance": provenance or {},
            "elapsed_ms": (time.perf_counter() - started) * 1000 if started else 0.0,
            "truncated": bool(truncated)}


# 类说明：`AgentTools` 封装本模块内聚的数据和行为。
class AgentTools:
    # 方法说明：`__init__` 完成当前步骤的业务处理；参数为 `database`、`cfg`、`retriever`、`service_manifest`。
    def __init__(self, database, cfg, retriever, service_manifest):
        self.db = database
        self.cfg = cfg
        self.retriever = retriever
        self.service_manifest = service_manifest
        self.metrics = MetricsStore((cfg.get("tools") or {}).get("metrics_path"))

    # 方法说明：`detect_anomaly` 完成当前步骤的业务处理；参数为 `event_id`。
    def detect_anomaly(self, event_id):
        started = time.perf_counter()
        event = self.db.one("SELECT * FROM events WHERE event_id=?", (event_id,))
        if not event:
            return result(error={"code": "EVENT_NOT_FOUND", "message": "Event was not found",
                                 "retryable": False}, started=started)
        sessions = self.db.all(
            "SELECT s.* FROM sessions s JOIN event_sessions e ON e.batch_id=s.batch_id "
            "AND e.session_id=s.session_id WHERE e.event_id=? ORDER BY s.session_id",
            (event_id,),
        )
        return result({"event": event, "sessions": sessions,
                       "model": {name: self.service_manifest[name] for name in (
                           "release_id", "model_id", "threshold")}},
                      provenance={"release_id": self.service_manifest["release_id"]},
                      started=started)

    # 方法说明：`query_logs` 完成当前步骤的业务处理；参数为 `event_id`、`limit`。
    def query_logs(self, event_id, limit=200):
        started = time.perf_counter()
        event = self.db.one("SELECT batch_id,start_time,end_time FROM events WHERE event_id=?",
                            (event_id,))
        if not event:
            return result(error={"code": "EVENT_NOT_FOUND", "message": "Event was not found",
                                 "retryable": False}, started=started)
        members = {row["session_id"] for row in self.db.all(
            "SELECT session_id FROM event_sessions WHERE event_id=?", (event_id,))}
        windowed = self.db.one(
            "SELECT value FROM event_metadata WHERE event_id=? AND name='window_seconds'",
            (event_id,))
        batch = self.db.one("SELECT status,artifact_dir FROM batches WHERE batch_id=?",
                            (event["batch_id"],))
        if not batch or batch["status"] != "SUCCEEDED" or not batch["artifact_dir"]:
            return result(error={"code": "BATCH_NOT_READY", "message": "Batch is not ready",
                                 "retryable": True}, started=started)
        path = Path(batch["artifact_dir"]) / "logs.parquet"
        rows, total = [], 0
        for batch_rows in pq.ParquetFile(path).iter_batches(batch_size=10000):
            for row in batch_rows.to_pylist():
                if not members.intersection(row.get("session_ids") or []):
                    continue
                stamp = row.get("timestamp")
                if windowed:
                    if event["start_time"] and stamp and stamp < event["start_time"]:
                        continue
                    if event["end_time"] and stamp and stamp >= event["end_time"]:
                        continue
                total += 1
                if len(rows) < int(limit):
                    rows.append({name: row.get(name) for name in (
                        "log_id", "timestamp", "level", "component", "redacted_message",
                        "template_id", "session_ids")})
        return result({"items": rows, "total": total},
                      provenance={"batch_id": event["batch_id"], "event_id": event_id},
                      started=started, truncated=total > len(rows))

    # 方法说明：`query_metrics` 查询事件窗口内的真实指标，缺少指标文件时保持 not_available。
    def query_metrics(self, event_id):
        started = time.perf_counter()
        event = self.db.one("SELECT * FROM events WHERE event_id=?", (event_id,))
        if not event:
            return result(error={"code": "EVENT_NOT_FOUND", "message": "Event was not found",
                                 "retryable": False}, started=started)
        store = getattr(self, "metrics", None)
        series = store.window(event.get("host_alias"), event.get("start_time"),
                              event.get("end_time")) if store else []
        if not series:
            return result({"status": "not_available", "event_id": event_id, "series": []},
                          provenance={"source": "metrics_store" if store and store.available
                                      else "not_configured"}, started=started)
        return result({"status": "available", "event_id": event_id,
                       "window": {"start": event.get("start_time"),
                                  "end": event.get("end_time")},
                       "series": series},
                      provenance={"source": str(store.path), "event_id": event_id},
                      started=started)

    # 方法说明：`search_similar_incidents` 完成当前步骤的业务处理；参数为 `diagnosis_id`、`event`、`summary`、`top_k`。
    def search_similar_incidents(self, diagnosis_id, event, summary, top_k=5):
        started = time.perf_counter()
        candidates = self.db.all(
            "SELECT r.report_json,a.event_id FROM incident_reports r JOIN agent_runs a "
            "ON a.diagnosis_id=r.diagnosis_id WHERE a.diagnosis_id<>? "
            "AND a.status IN ('COMPLETED','APPROVED_REPORT') ORDER BY r.created_at",
            (diagnosis_id,),
        )
        query_tokens = set(tokenize(summary))
        ranked = []
        for row in candidates:
            body = json.loads(row["report_json"])
            observed_end = body.get("observation_window", {}).get("end")
            if observed_end and event.get("start_time") and observed_end > event["start_time"]:
                continue
            text = body.get("summary", "")
            tokens = set(tokenize(text))
            score = len(query_tokens & tokens) / max(1, len(query_tokens | tokens))
            if score:
                ranked.append({"incident_id": row["event_id"], "report_id": body["report_id"],
                               "similarity": score, "summary": text,
                               "closed_at": body["provenance"].get("generated_at")})
        ranked.sort(key=lambda item: (-item["similarity"], item["report_id"]))
        return result({"items": ranked[:int(top_k)]},
                      provenance={"as_of_time": event.get("start_time")}, started=started)

    # 方法说明：`retrieve_runbook` 完成检索；`code` 为证据命中的根因码，用于硬过滤。
    def retrieve_runbook(self, query, component=None, product_version=None, top_k=3, code=None):
        started = time.perf_counter()
        try:
            try:
                found = self.retriever.search(query, mode="frozen", top_k=int(top_k),
                                              component=component,
                                              product_version=product_version, code=code)
            except TypeError:
                found = self.retriever.search(query, mode="frozen", top_k=int(top_k),
                                              component=component,
                                              product_version=product_version)
        except ValueError as exc:
            return result(error={"code": "INVALID_RETRIEVAL", "message": str(exc),
                                 "retryable": False}, started=started)
        return result(found, provenance={"kb_release_id":
                      self.retriever.manifest["kb_release_id"]}, started=started)

    # 变量说明：CODE_SIGNALS 是根因码对应的日志特征词，用于同组件内互斥排序。
    CODE_SIGNALS = {"DN_VOLUME": ("no space left", "volume failed", "failed volume",
                                  "disk full"),
                    "NETWORK_CONNECTIVITY": ("connection timed out", "no route to host",
                                             "network is unreachable", "connection reset",
                                             "retrying connect"),
                    "NN_AVAILABILITY": ("connection refused", "failed to connect",
                                        "retrying connect"),
                    "DN_HEARTBEAT": ("lost heartbeat", "lost datanode",
                                     "dead datanode", "removedead"),
                    "NN_SAFE_MODE": ("safe mode",)}

    # 变量说明：WEAK_TERMS 是无强信号时的弱先验词，只用于候选内重排。
    WEAK_TERMS = {"DN_VOLUME": ("volume", "disk", "space", "磁盘", "卷"),
                  "NETWORK_CONNECTIVITY": ("network", "connection", "timeout",
                                           "unreachable", "retrying"),
                  "DN_HEARTBEAT": ("heartbeat", "dead", "lost", "心跳", "失联"),
                  "NN_SAFE_MODE": ("safe mode", "safemode", "安全模式")}

    # 方法说明：`rank_root_causes` 完成当前步骤的业务处理；参数为 `log_evidence`、`doc_evidence`、`components`。
    @staticmethod
    def rank_root_causes(log_evidence, doc_evidence, components):
        started = time.perf_counter()
        messages = " ".join((row.get("excerpt_redacted") or "")
                            for row in log_evidence).lower()
        matched = {code for code, signals in AgentTools.CODE_SIGNALS.items()
                   if any(signal in messages for signal in signals)}
        weak = {code: sum(messages.count(word) for word in words)
                for code, words in AgentTools.WEAK_TERMS.items()}
        ordered = sorted(enumerate(doc_evidence),
                         key=lambda item: (0 if item[1].get("root_cause_code") in matched
                                           else 1,
                                           -weak.get(item[1].get("root_cause_code"), 0),
                                           item[0]))
        doc_evidence = [document for _, document in ordered]
        hypotheses = []
        for index, document in enumerate(doc_evidence[:5], 1):
            component = document.get("component") or (components[0] if components else None)
            support = [document["evidence_id"]]
            support.extend(row["evidence_id"] for row in log_evidence
                           if not component or row.get("component") == component)
            score = min(1.0, 0.35 + 0.1 * min(4, len(support)))
            confidence = "medium" if len(support) >= 2 else "low"
            hypotheses.append({
                "hypothesis_id": f"hyp_{index}",
                "description": "待验证候选：" + document.get("title", "知识条目所述异常"),
                "component": component, "root_cause_code": document.get("root_cause_code"),
                "support_ids": support[:12], "counter_ids": [],
                "missing_checks": ["需要结合更多运行指标或人工现场信息确认"],
                "support_score": score, "confidence_level": confidence,
            })
        if not hypotheses:
            hypotheses.append({
                "hypothesis_id": "hyp_unknown", "description": "现有证据不足以形成可验证候选",
                "component": components[0] if components else None,
                "support_ids": [row["evidence_id"] for row in log_evidence[:3]],
                "counter_ids": [], "missing_checks": ["补充适用手册和相关时间窗口证据"],
                "support_score": 0.0, "confidence_level": "unknown",
            })
        return result({"hypotheses": hypotheses}, started=started)


# 方法说明：`log_evidence` 完成当前步骤的业务处理；参数为 `row`、`version`。
def log_evidence(row, version):
    evidence_id = "evd_log_" + key([row["log_id"], row.get("timestamp"),
                                     row.get("redacted_message")])[:20]
    return {"evidence_id": evidence_id, "kind": "log", "source_ref": row["log_id"],
            "version": version, "observed_at": row.get("timestamp"),
            "excerpt_redacted": row.get("redacted_message") or "",
            "evidence_hash": key(row), "component": row.get("component"),
            "level": row.get("level"), "template_id": row.get("template_id")}


# 方法说明：`document_evidence` 完成当前步骤的业务处理；参数为 `row`、`version`。
def document_evidence(row, version):
    component = row.get("component")
    if isinstance(component, list):
        component = component[0] if component else None
    codes = row.get("root_cause_codes") or []
    return {"evidence_id": row["chunk_id"], "kind": "doc",
            "source_ref": row["doc_id"], "version": version, "observed_at": None,
            "excerpt_redacted": row["text"], "evidence_hash": key(row),
            "component": component, "title": row.get("title"),
            "root_cause_code": row.get("root_cause_code") or (codes[0] if codes else None),
            "section_path": row.get("section_path"), "source_url": row.get("source_url")}
