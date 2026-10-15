import json
import time
from pathlib import Path

import pyarrow.parquet as pq

from aiops_diag.data.common import key
from aiops_diag.retrieval.engine import tokenize


def result(data=None, error=None, provenance=None, started=None, truncated=False):
    return {"ok": error is None, "data": data or {}, "error": error,
            "provenance": provenance or {},
            "elapsed_ms": (time.perf_counter() - started) * 1000 if started else 0.0,
            "truncated": bool(truncated)}


class AgentTools:
    def __init__(self, database, cfg, retriever, service_manifest):
        self.db = database
        self.cfg = cfg
        self.retriever = retriever
        self.service_manifest = service_manifest

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

    def query_logs(self, event_id, limit=200):
        started = time.perf_counter()
        event = self.db.one("SELECT batch_id FROM events WHERE event_id=?", (event_id,))
        if not event:
            return result(error={"code": "EVENT_NOT_FOUND", "message": "Event was not found",
                                 "retryable": False}, started=started)
        members = {row["session_id"] for row in self.db.all(
            "SELECT session_id FROM event_sessions WHERE event_id=?", (event_id,))}
        batch = self.db.one("SELECT status,artifact_dir FROM batches WHERE batch_id=?",
                            (event["batch_id"],))
        if not batch or batch["status"] != "SUCCEEDED" or not batch["artifact_dir"]:
            return result(error={"code": "BATCH_NOT_READY", "message": "Batch is not ready",
                                 "retryable": True}, started=started)
        path = Path(batch["artifact_dir"]) / "logs.parquet"
        rows, total = [], 0
        for batch_rows in pq.ParquetFile(path).iter_batches(batch_size=10000):
            for row in batch_rows.to_pylist():
                if members.intersection(row.get("session_ids") or []):
                    total += 1
                    if len(rows) < int(limit):
                        rows.append({name: row.get(name) for name in (
                            "log_id", "timestamp", "level", "component", "redacted_message",
                            "template_id", "session_ids")})
        return result({"items": rows, "total": total},
                      provenance={"batch_id": event["batch_id"], "event_id": event_id},
                      started=started, truncated=total > len(rows))

    @staticmethod
    def query_metrics(event_id):
        started = time.perf_counter()
        return result({"status": "not_available", "event_id": event_id, "series": []},
                      provenance={"source": "not_configured"}, started=started)

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

    def retrieve_runbook(self, query, component=None, product_version=None, top_k=3):
        started = time.perf_counter()
        try:
            found = self.retriever.search(query, mode="frozen", top_k=int(top_k),
                                          component=component,
                                          product_version=product_version)
        except ValueError as exc:
            return result(error={"code": "INVALID_RETRIEVAL", "message": str(exc),
                                 "retryable": False}, started=started)
        return result(found, provenance={"kb_release_id":
                      self.retriever.manifest["kb_release_id"]}, started=started)

    @staticmethod
    def rank_root_causes(log_evidence, doc_evidence, components):
        started = time.perf_counter()
        hypotheses = []
        for index, document in enumerate(doc_evidence[:3], 1):
            component = document.get("component") or (components[0] if components else None)
            support = [document["evidence_id"]]
            support.extend(row["evidence_id"] for row in log_evidence
                           if not component or row.get("component") == component)
            score = min(1.0, 0.35 + 0.1 * min(4, len(support)))
            confidence = "medium" if len(support) >= 2 else "low"
            hypotheses.append({
                "hypothesis_id": f"hyp_{index}",
                "description": "待验证候选：" + document.get("title", "知识条目所述异常"),
                "component": component, "support_ids": support[:12], "counter_ids": [],
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


def log_evidence(row, version):
    evidence_id = "evd_log_" + key([row["log_id"], row.get("timestamp"),
                                     row.get("redacted_message")])[:20]
    return {"evidence_id": evidence_id, "kind": "log", "source_ref": row["log_id"],
            "version": version, "observed_at": row.get("timestamp"),
            "excerpt_redacted": row.get("redacted_message") or "",
            "evidence_hash": key(row), "component": row.get("component"),
            "level": row.get("level"), "template_id": row.get("template_id")}


def document_evidence(row, version):
    component = row.get("component")
    if isinstance(component, list):
        component = component[0] if component else None
    return {"evidence_id": row["chunk_id"], "kind": "doc",
            "source_ref": row["doc_id"], "version": version, "observed_at": None,
            "excerpt_redacted": row["text"], "evidence_hash": key(row),
            "component": component, "title": row.get("title"),
            "section_path": row.get("section_path"), "source_url": row.get("source_url")}
