import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta(version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS batches(
  batch_id TEXT PRIMARY KEY, source_kind TEXT NOT NULL, source_ref TEXT NOT NULL,
  input_hash TEXT NOT NULL, release_id TEXT NOT NULL, processing_hash TEXT NOT NULL,
  status TEXT NOT NULL, artifact_dir TEXT, total_lines INTEGER NOT NULL DEFAULT 0,
  parsed_lines INTEGER NOT NULL DEFAULT 0, quarantined_lines INTEGER NOT NULL DEFAULT 0,
  session_count INTEGER NOT NULL DEFAULT 0, anomaly_count INTEGER NOT NULL DEFAULT 0,
  event_count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(input_hash, release_id, processing_hash)
);
CREATE TABLE IF NOT EXISTS tasks(
  task_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(batch_id),
  status TEXT NOT NULL, stage TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  error_code TEXT, error_message TEXT, created_at TEXT NOT NULL, started_at TEXT,
  finished_at TEXT, updated_at TEXT NOT NULL, lease_owner TEXT, lease_token TEXT,
  lease_expires_at TEXT
);
CREATE TABLE IF NOT EXISTS idempotency_keys(
  idempotency_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
  task_id TEXT NOT NULL REFERENCES tasks(task_id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions(
  batch_id TEXT NOT NULL REFERENCES batches(batch_id), session_id TEXT NOT NULL,
  start_time TEXT, end_time TEXT, line_count INTEGER NOT NULL, unknown_count INTEGER NOT NULL,
  anomaly_score REAL NOT NULL, threshold REAL NOT NULL, prediction INTEGER NOT NULL,
  first_log_id TEXT, last_log_id TEXT, host_alias TEXT, PRIMARY KEY(batch_id, session_id)
);
CREATE TABLE IF NOT EXISTS events(
  event_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(batch_id),
  host_alias TEXT, start_time TEXT, end_time TEXT, detected_at TEXT NOT NULL,
  max_anomaly_score REAL NOT NULL, threshold REAL NOT NULL, session_count INTEGER NOT NULL,
  status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_batch_time ON events(batch_id, start_time, event_id);
CREATE TABLE IF NOT EXISTS event_metadata(
  event_id TEXT NOT NULL REFERENCES events(event_id), name TEXT NOT NULL, value TEXT NOT NULL,
  PRIMARY KEY(event_id,name)
);
CREATE TABLE IF NOT EXISTS event_sessions(
  event_id TEXT NOT NULL REFERENCES events(event_id), batch_id TEXT NOT NULL,
  session_id TEXT NOT NULL, PRIMARY KEY(event_id, session_id),
  FOREIGN KEY(batch_id, session_id) REFERENCES sessions(batch_id, session_id)
);
CREATE TABLE IF NOT EXISTS artifacts(
  batch_id TEXT NOT NULL REFERENCES batches(batch_id), name TEXT NOT NULL,
  relative_path TEXT NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(batch_id, name)
);
CREATE TABLE IF NOT EXISTS audit_records(
  audit_id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, action TEXT NOT NULL,
  details_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workers(
  worker_id TEXT PRIMARY KEY, release_id TEXT NOT NULL, status TEXT NOT NULL,
  started_at TEXT NOT NULL, heartbeat_at TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS rag_reports(
  report_id TEXT PRIMARY KEY, query_hash TEXT NOT NULL, request_fingerprint TEXT NOT NULL,
  status TEXT NOT NULL, report_json TEXT NOT NULL, report_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rag_reports_query ON rag_reports(query_hash,created_at);
CREATE TABLE IF NOT EXISTS rag_idempotency_keys(
  idempotency_key TEXT PRIMARY KEY, request_fingerprint TEXT NOT NULL,
  report_id TEXT NOT NULL REFERENCES rag_reports(report_id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_runs(
  diagnosis_id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(event_id),
  revision INTEGER NOT NULL, parent_diagnosis_id TEXT,
  mode TEXT NOT NULL, status TEXT NOT NULL, current_node TEXT NOT NULL,
  state_json TEXT NOT NULL DEFAULT '{}', budget_json TEXT NOT NULL DEFAULT '{}',
  report_id TEXT, approval_id TEXT, release_id TEXT NOT NULL,
  request_fingerprint TEXT NOT NULL, error_code TEXT, error_message TEXT,
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, updated_at TEXT NOT NULL,
  lease_owner TEXT, lease_token TEXT, lease_expires_at TEXT,
  UNIQUE(event_id,revision,release_id)
);
CREATE TABLE IF NOT EXISTS agent_idempotency_keys(
  idempotency_key TEXT PRIMARY KEY, request_fingerprint TEXT NOT NULL,
  diagnosis_id TEXT NOT NULL REFERENCES agent_runs(diagnosis_id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_tool_calls(
  tool_call_id TEXT PRIMARY KEY, diagnosis_id TEXT NOT NULL REFERENCES agent_runs(diagnosis_id),
  ordinal INTEGER NOT NULL, tool_name TEXT NOT NULL, args_hash TEXT NOT NULL,
  args_json TEXT NOT NULL, status TEXT NOT NULL, result_json TEXT,
  started_at TEXT NOT NULL, finished_at TEXT,
  UNIQUE(diagnosis_id,ordinal), UNIQUE(diagnosis_id,tool_name,args_hash)
);
CREATE TABLE IF NOT EXISTS agent_evidence(
  evidence_id TEXT NOT NULL, diagnosis_id TEXT NOT NULL REFERENCES agent_runs(diagnosis_id),
  kind TEXT NOT NULL, source_ref TEXT NOT NULL, version TEXT NOT NULL,
  observed_at TEXT, excerpt_redacted TEXT NOT NULL, evidence_hash TEXT NOT NULL,
  PRIMARY KEY(diagnosis_id,evidence_id)
);
CREATE TABLE IF NOT EXISTS incident_reports(
  report_id TEXT PRIMARY KEY, diagnosis_id TEXT NOT NULL UNIQUE REFERENCES agent_runs(diagnosis_id),
  revision INTEGER NOT NULL, status TEXT NOT NULL, report_json TEXT NOT NULL,
  report_markdown TEXT NOT NULL, report_hash TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals(
  approval_id TEXT PRIMARY KEY, diagnosis_id TEXT NOT NULL REFERENCES agent_runs(diagnosis_id),
  report_id TEXT NOT NULL REFERENCES incident_reports(report_id), report_hash TEXT NOT NULL,
  revision INTEGER NOT NULL, action_ids_json TEXT NOT NULL, status TEXT NOT NULL,
  reviewer_id TEXT, reason TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  decided_at TEXT, idempotency_key TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status,created_at);
CREATE TABLE IF NOT EXISTS agent_audit_records(
  audit_id INTEGER PRIMARY KEY AUTOINCREMENT, diagnosis_id TEXT,
  actor_type TEXT NOT NULL, actor_id TEXT, action TEXT NOT NULL,
  details_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_usage(
  provider TEXT PRIMARY KEY, input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0, estimated_cost_cny REAL NOT NULL DEFAULT 0,
  calls INTEGER NOT NULL DEFAULT 0, imported_legacy INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_reservations(
  reservation_id TEXT PRIMARY KEY, provider TEXT NOT NULL REFERENCES provider_usage(provider),
  scope TEXT NOT NULL, reserved_tokens INTEGER NOT NULL, reserved_cost_cny REAL NOT NULL,
  status TEXT NOT NULL, created_at TEXT NOT NULL, settled_at TEXT
);
"""


class IdempotencyConflict(ValueError):
    pass


class QueueFull(RuntimeError):
    pass


class LeaseLost(RuntimeError):
    pass


class ApprovalConflict(ValueError):
    pass


class ApprovalExpired(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def _deadline(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


class Database:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def init(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = self.connect()
        try:
            db.executescript(SCHEMA)

            evidence_info = db.execute("PRAGMA table_info(agent_evidence)").fetchall()
            evidence_pk = [row[1] for row in sorted(
                (row for row in evidence_info if row[5]), key=lambda row: row[5])]
            if evidence_pk == ["evidence_id"]:
                db.execute("ALTER TABLE agent_evidence RENAME TO agent_evidence_legacy")
                db.execute(
                    "CREATE TABLE agent_evidence("
                    "evidence_id TEXT NOT NULL,diagnosis_id TEXT NOT NULL "
                    "REFERENCES agent_runs(diagnosis_id),kind TEXT NOT NULL,"
                    "source_ref TEXT NOT NULL,version TEXT NOT NULL,observed_at TEXT,"
                    "excerpt_redacted TEXT NOT NULL,evidence_hash TEXT NOT NULL,"
                    "PRIMARY KEY(diagnosis_id,evidence_id))")
                db.execute(
                    "INSERT INTO agent_evidence SELECT evidence_id,diagnosis_id,kind,"
                    "source_ref,version,observed_at,excerpt_redacted,evidence_hash "
                    "FROM agent_evidence_legacy")
                db.execute("DROP TABLE agent_evidence_legacy")
            task_columns = {row[1] for row in db.execute("PRAGMA table_info(tasks)")}
            for name in ("lease_owner", "lease_token", "lease_expires_at"):
                if name not in task_columns:
                    db.execute(f"ALTER TABLE tasks ADD COLUMN {name} TEXT")
            rows = db.execute("SELECT version FROM schema_meta").fetchall()
            if not rows:
                db.execute("INSERT INTO schema_meta(version) VALUES (4)")
            elif len(rows) != 1 or rows[0][0] not in (1, 2, 3, 4):
                raise ValueError("Unsupported service database schema")
            else:
                db.execute("UPDATE schema_meta SET version=4")
        finally:
            db.close()

    def set_event_metadata(self, event_id, values):
        allowed = {"product_version"}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError("Unsupported event metadata")
        with self.transaction() as db:
            if not db.execute("SELECT 1 FROM events WHERE event_id=?", (event_id,)).fetchone():
                raise FileNotFoundError("Event was not found")
            db.executemany(
                "INSERT INTO event_metadata(event_id,name,value) VALUES (?,?,?) "
                "ON CONFLICT(event_id,name) DO UPDATE SET value=excluded.value",
                ((event_id, name, str(value)) for name, value in values.items()
                 if value is not None),
            )

    def get_event_metadata(self, event_id):
        return {row["name"]: row["value"] for row in self.all(
            "SELECT name,value FROM event_metadata WHERE event_id=? ORDER BY name", (event_id,))}

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _dict(row):
        return None if row is None else dict(row)

    @staticmethod
    def _audit(db, task_id, action, details, stamp):
        db.execute(
            "INSERT INTO audit_records(task_id,action,details_json,created_at) VALUES (?,?,?,?)",
            (task_id, action, json.dumps(details, separators=(",", ":")), stamp),
        )

    def create_task(self, batch_id, task_id, source_kind, source_ref, input_hash,
                    release_id, processing_hash, fingerprint, idempotency_key=None,
                    max_inflight=32):
        stamp = now()
        with self.transaction() as db:
            if idempotency_key:
                found = db.execute(
                    "SELECT fingerprint,task_id FROM idempotency_keys WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if found:
                    if found["fingerprint"] != fingerprint:
                        raise IdempotencyConflict("Idempotency-Key was already used for another request")
                    return self._dict(db.execute(
                        "SELECT * FROM tasks WHERE task_id=?", (found["task_id"],)
                    ).fetchone()), True
            existing = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if existing:
                if idempotency_key:
                    db.execute("INSERT INTO idempotency_keys VALUES (?,?,?,?)",
                               (idempotency_key, fingerprint, task_id, stamp))
                return self._dict(existing), True
            inflight = db.execute(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('QUEUED','RUNNING')"
            ).fetchone()[0]
            if inflight >= int(max_inflight):
                raise QueueFull("Task queue reached its configured capacity")
            db.execute(
                "INSERT INTO batches(batch_id,source_kind,source_ref,input_hash,release_id,"
                "processing_hash,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (batch_id, source_kind, source_ref, input_hash, release_id,
                 processing_hash, "QUEUED", stamp, stamp),
            )
            db.execute(
                "INSERT INTO tasks(task_id,batch_id,status,stage,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?)", (task_id, batch_id, "QUEUED", "VALIDATING", stamp, stamp),
            )
            if idempotency_key:
                db.execute("INSERT INTO idempotency_keys VALUES (?,?,?,?)",
                           (idempotency_key, fingerprint, task_id, stamp))
            self._audit(db, task_id, "TASK_CREATED", {"source_kind": source_kind}, stamp)
            return self._dict(db.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()), False

    def heartbeat(self, worker_id, release_id, status="READY", details=None):
        stamp = now()
        payload = json.dumps(details or {}, separators=(",", ":"))
        with self.transaction() as db:
            db.execute(
                "INSERT INTO workers(worker_id,release_id,status,started_at,heartbeat_at,details_json) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(worker_id) DO UPDATE SET release_id=excluded.release_id,"
                "status=excluded.status,heartbeat_at=excluded.heartbeat_at,details_json=excluded.details_json",
                (worker_id, release_id, status, stamp, stamp, payload),
            )

    def worker_ready(self, release_id, max_age_seconds=15):
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)).isoformat()
        return self.one(
            "SELECT worker_id,status,heartbeat_at FROM workers WHERE release_id=? AND status='READY' "
            "AND heartbeat_at>=? ORDER BY heartbeat_at DESC LIMIT 1", (release_id, cutoff),
        )

    def claim(self, worker_id=None, lease_seconds=30):
        stamp = now()
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM tasks WHERE status='QUEUED' ORDER BY created_at,task_id LIMIT 1"
            ).fetchone()
            if not row:
                return None
            token = uuid.uuid4().hex if worker_id else None
            expires = _deadline(lease_seconds) if worker_id else None
            updated = db.execute(
                "UPDATE tasks SET status='RUNNING',stage='VALIDATING',attempts=attempts+1,"
                "started_at=COALESCE(started_at,?),updated_at=?,lease_owner=?,lease_token=?,"
                "lease_expires_at=? WHERE task_id=? AND status='QUEUED'",
                (stamp, stamp, worker_id, token, expires, row["task_id"]),
            ).rowcount
            if updated != 1:
                return None
            db.execute("UPDATE batches SET status='RUNNING',updated_at=? WHERE batch_id=?",
                       (stamp, row["batch_id"]))
            self._audit(db, row["task_id"], "TASK_CLAIMED",
                        {"worker_id": worker_id}, stamp)
            return self._dict(db.execute(
                "SELECT t.*,b.source_kind,b.source_ref,b.input_hash,b.release_id,b.processing_hash "
                "FROM tasks t JOIN batches b USING(batch_id) WHERE task_id=?", (row["task_id"],)
            ).fetchone())

    def renew(self, task_id, lease_token, lease_seconds=30):
        db = self.connect()
        try:
            changed = db.execute(
                "UPDATE tasks SET lease_expires_at=?,updated_at=? WHERE task_id=? AND status='RUNNING' "
                "AND lease_token=?", (_deadline(lease_seconds), now(), task_id, lease_token),
            ).rowcount
            if changed != 1:
                raise LeaseLost("Task lease is no longer owned by this worker")
        finally:
            db.close()

    def recover_expired(self):
        stamp = now()
        recovered = 0
        with self.transaction() as db:
            rows = db.execute(
                "SELECT task_id,batch_id FROM tasks WHERE status='RUNNING' AND lease_expires_at IS NOT NULL "
                "AND lease_expires_at<?", (stamp,),
            ).fetchall()
            for row in rows:
                db.execute(
                    "UPDATE tasks SET status='QUEUED',stage='VALIDATING',lease_owner=NULL,"
                    "lease_token=NULL,lease_expires_at=NULL,updated_at=? WHERE task_id=?",
                    (stamp, row["task_id"]),
                )
                db.execute("UPDATE batches SET status='QUEUED',updated_at=? WHERE batch_id=?",
                           (stamp, row["batch_id"]))
                self._audit(db, row["task_id"], "TASK_LEASE_RECOVERED", {}, stamp)
                recovered += 1
        return recovered

    def recover(self):
        """Legacy explicit recovery used by W5 callers and migration tests."""
        stamp = now()
        with self.transaction() as db:
            rows = db.execute("SELECT task_id,batch_id FROM tasks WHERE status='RUNNING'").fetchall()
            for row in rows:
                db.execute(
                    "UPDATE tasks SET status='QUEUED',stage='VALIDATING',lease_owner=NULL,"
                    "lease_token=NULL,lease_expires_at=NULL,updated_at=? WHERE task_id=?",
                    (stamp, row["task_id"]),
                )
                db.execute("UPDATE batches SET status='QUEUED',updated_at=? WHERE batch_id=?",
                           (stamp, row["batch_id"]))
                self._audit(db, row["task_id"], "TASK_RECOVERED", {}, stamp)
        return len(rows)

    def set_stage(self, task_id, stage, lease_token=None):
        db = self.connect()
        try:
            sql = "UPDATE tasks SET stage=?,updated_at=? WHERE task_id=? AND status='RUNNING'"
            params = [stage, now(), task_id]
            if lease_token is not None:
                sql += " AND lease_token=?"
                params.append(lease_token)
            if db.execute(sql, params).rowcount != 1:
                raise LeaseLost("Task lease was lost while updating its stage")
        finally:
            db.close()

    def fail(self, task_id, code, message, lease_token=None):
        stamp = now()
        with self.transaction() as db:
            sql = "SELECT batch_id FROM tasks WHERE task_id=? AND status='RUNNING'"
            params = [task_id]
            if lease_token is not None:
                sql += " AND lease_token=?"
                params.append(lease_token)
            row = db.execute(sql, params).fetchone()
            if not row:
                raise LeaseLost("Task lease was lost before failure could be recorded")
            db.execute(
                "UPDATE tasks SET status='FAILED',error_code=?,error_message=?,finished_at=?,"
                "updated_at=?,lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL WHERE task_id=?",
                (code, str(message)[:2000], stamp, stamp, task_id),
            )
            db.execute("UPDATE batches SET status='FAILED',updated_at=? WHERE batch_id=?",
                       (stamp, row["batch_id"]))
            self._audit(db, task_id, "TASK_FAILED", {"code": code}, stamp)

    def complete(self, task_id, artifact_dir, counts, sessions, events, event_members, artifacts,
                 lease_token=None):
        stamp = now()
        with self.transaction() as db:
            sql = "SELECT batch_id FROM tasks WHERE task_id=? AND status='RUNNING'"
            params = [task_id]
            if lease_token is not None:
                sql += " AND lease_token=?"
                params.append(lease_token)
            task = db.execute(sql, params).fetchone()
            if not task:
                raise LeaseLost("Task lease was lost before completion")
            batch_id = task["batch_id"]
            db.execute("DELETE FROM event_sessions WHERE batch_id=?", (batch_id,))
            db.execute(
                "DELETE FROM event_metadata WHERE event_id IN "
                "(SELECT event_id FROM events WHERE batch_id=?)", (batch_id,))
            db.execute("DELETE FROM events WHERE batch_id=?", (batch_id,))
            db.execute("DELETE FROM sessions WHERE batch_id=?", (batch_id,))
            db.execute("DELETE FROM artifacts WHERE batch_id=?", (batch_id,))
            db.executemany(
                "INSERT INTO sessions(batch_id,session_id,start_time,end_time,line_count,unknown_count,"
                "anomaly_score,threshold,prediction,first_log_id,last_log_id,host_alias) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ((batch_id, row["session_id"], row.get("start_time"), row.get("end_time"),
                  row["line_count"], row["unknown_count"], row["anomaly_score"], row["threshold"],
                  row["prediction"], row.get("first_log_id"), row.get("last_log_id"),
                  row.get("host_alias")) for row in sessions),
            )
            db.executemany(
                "INSERT INTO events(event_id,batch_id,host_alias,start_time,end_time,detected_at,"
                "max_anomaly_score,threshold,session_count,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
                ((row["event_id"], batch_id, row.get("host_alias"), row.get("start_time"),
                  row.get("end_time"), row["detected_at"], row["max_anomaly_score"],
                  row["threshold"], row["session_count"], row["status"]) for row in events),
            )
            db.executemany(
                "INSERT INTO event_sessions(event_id,batch_id,session_id) VALUES (?,?,?)",
                ((row["event_id"], batch_id, row["session_id"]) for row in event_members),
            )
            db.executemany(
                "INSERT INTO artifacts(batch_id,name,relative_path,sha256) VALUES (?,?,?,?)",
                ((batch_id, name, item["relative_path"], item["sha256"])
                 for name, item in artifacts.items()),
            )
            db.execute(
                "UPDATE batches SET status='SUCCEEDED',artifact_dir=?,total_lines=?,parsed_lines=?,"
                "quarantined_lines=?,session_count=?,anomaly_count=?,event_count=?,updated_at=? "
                "WHERE batch_id=?",
                (str(artifact_dir), counts["total_lines"], counts["parsed_lines"],
                 counts["quarantined_lines"], counts["session_count"], counts["anomaly_count"],
                 counts["event_count"], stamp, batch_id),
            )
            db.execute(
                "UPDATE tasks SET status='SUCCEEDED',stage='COMPLETED',finished_at=?,updated_at=?,"
                "lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL WHERE task_id=?",
                (stamp, stamp, task_id),
            )
            self._audit(db, task_id, "TASK_SUCCEEDED", counts, stamp)

    def operation_summary(self, release_id, heartbeat_age=15):
        counts = {row["status"]: row["n"] for row in self.all(
            "SELECT status,COUNT(*) AS n FROM tasks GROUP BY status"
        )}
        oldest = self.one("SELECT created_at FROM tasks WHERE status='QUEUED' ORDER BY created_at LIMIT 1")
        latest = self.one(
            "SELECT finished_at FROM tasks WHERE finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 1"
        )
        wait = None
        if oldest:
            wait = max(0.0, (datetime.now(timezone.utc) -
                             datetime.fromisoformat(oldest["created_at"])).total_seconds())
        worker = self.worker_ready(release_id, heartbeat_age)
        return {
            "release_id": release_id, "worker_ready": worker is not None,
            "worker_heartbeat_at": worker["heartbeat_at"] if worker else None,
            "queued": counts.get("QUEUED", 0), "running": counts.get("RUNNING", 0),
            "succeeded": counts.get("SUCCEEDED", 0), "failed": counts.get("FAILED", 0),
            "oldest_queue_seconds": wait,
            "last_finished_at": latest["finished_at"] if latest else None,
        }

    def save_rag_report(self, report, request_fingerprint, idempotency_key=None):
        stamp = now()
        payload = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.transaction() as db:
            if idempotency_key:
                found = db.execute(
                    "SELECT request_fingerprint,report_id FROM rag_idempotency_keys "
                    "WHERE idempotency_key=?", (idempotency_key,),
                ).fetchone()
                if found:
                    if found["request_fingerprint"] != request_fingerprint:
                        raise IdempotencyConflict(
                            "Idempotency-Key was already used for another RAG request")
                    existing = db.execute("SELECT report_json FROM rag_reports WHERE report_id=?",
                                          (found["report_id"],)).fetchone()
                    return json.loads(existing["report_json"]), True
            db.execute(
                "INSERT OR IGNORE INTO rag_reports(report_id,query_hash,request_fingerprint,status,"
                "report_json,report_hash,created_at) VALUES (?,?,?,?,?,?,?)",
                (report["report_id"], report["provenance"]["query_hash"], request_fingerprint,
                 report["status"], payload, report["report_hash"], stamp),
            )
            if idempotency_key:
                db.execute("INSERT INTO rag_idempotency_keys VALUES (?,?,?,?)",
                           (idempotency_key, request_fingerprint, report["report_id"], stamp))
            self._audit(db, None, "RAG_REPORT_CREATED",
                        {"report_id": report["report_id"], "query_hash":
                         report["provenance"]["query_hash"], "status": report["status"]}, stamp)
            return report, False

    def get_rag_report(self, report_id):
        row = self.one("SELECT report_json FROM rag_reports WHERE report_id=?", (report_id,))
        return json.loads(row["report_json"]) if row else None

    def create_agent_run(self, diagnosis_id, event_id, mode, release_id, fingerprint,
                         budget, idempotency_key=None, max_inflight=16, revision=1,
                         parent_diagnosis_id=None):
        stamp = now()
        with self.transaction() as db:
            if not db.execute("SELECT 1 FROM events WHERE event_id=?", (event_id,)).fetchone():
                raise FileNotFoundError("Event was not found")
            if idempotency_key:
                found = db.execute(
                    "SELECT request_fingerprint,diagnosis_id FROM agent_idempotency_keys "
                    "WHERE idempotency_key=?", (idempotency_key,),
                ).fetchone()
                if found:
                    if found["request_fingerprint"] != fingerprint:
                        raise IdempotencyConflict(
                            "Idempotency-Key was already used for another diagnosis")
                    return self._dict(db.execute(
                        "SELECT * FROM agent_runs WHERE diagnosis_id=?",
                        (found["diagnosis_id"],),
                    ).fetchone()), True
            existing = db.execute(
                "SELECT * FROM agent_runs WHERE event_id=? AND revision=? AND release_id=?",
                (event_id, revision, release_id),
            ).fetchone()
            if existing:
                if idempotency_key:
                    db.execute("INSERT INTO agent_idempotency_keys VALUES (?,?,?,?)",
                               (idempotency_key, fingerprint, existing["diagnosis_id"], stamp))
                return self._dict(existing), True
            inflight = db.execute(
                "SELECT COUNT(*) FROM agent_runs WHERE status IN ('QUEUED','RUNNING')"
            ).fetchone()[0]
            if inflight >= int(max_inflight):
                raise QueueFull("Agent queue reached its configured capacity")
            state = {"tool_calls": [], "evidence_ids": [], "errors": [],
                     "review_reasons": []}
            db.execute(
                "INSERT INTO agent_runs(diagnosis_id,event_id,revision,parent_diagnosis_id,mode,"
                "status,current_node,state_json,budget_json,release_id,request_fingerprint,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (diagnosis_id, event_id, revision, parent_diagnosis_id, mode, "QUEUED",
                 "RECEIVED", json.dumps(state, separators=(",", ":")),
                 json.dumps(budget, separators=(",", ":")), release_id, fingerprint,
                 stamp, stamp),
            )
            if idempotency_key:
                db.execute("INSERT INTO agent_idempotency_keys VALUES (?,?,?,?)",
                           (idempotency_key, fingerprint, diagnosis_id, stamp))
            self._agent_audit(db, diagnosis_id, "system", None, "AGENT_CREATED",
                              {"event_id": event_id, "revision": revision}, stamp)
            return self._dict(db.execute(
                "SELECT * FROM agent_runs WHERE diagnosis_id=?", (diagnosis_id,),
            ).fetchone()), False

    @staticmethod
    def _agent_audit(db, diagnosis_id, actor_type, actor_id, action, details, stamp):
        db.execute(
            "INSERT INTO agent_audit_records(diagnosis_id,actor_type,actor_id,action,"
            "details_json,created_at) VALUES (?,?,?,?,?,?)",
            (diagnosis_id, actor_type, actor_id, action,
             json.dumps(details, ensure_ascii=False, separators=(",", ":")), stamp),
        )

    def claim_agent(self, worker_id, lease_seconds=30):
        stamp = now()
        with self.transaction() as db:
            row = db.execute(
                "SELECT diagnosis_id FROM agent_runs WHERE status='QUEUED' "
                "ORDER BY created_at,diagnosis_id LIMIT 1"
            ).fetchone()
            if not row:
                return None
            token = uuid.uuid4().hex
            changed = db.execute(
                "UPDATE agent_runs SET status='RUNNING',started_at=COALESCE(started_at,?),"
                "updated_at=?,lease_owner=?,lease_token=?,lease_expires_at=? "
                "WHERE diagnosis_id=? AND status='QUEUED'",
                (stamp, stamp, worker_id, token, _deadline(lease_seconds),
                 row["diagnosis_id"]),
            ).rowcount
            if changed != 1:
                return None
            self._agent_audit(db, row["diagnosis_id"], "worker", worker_id,
                              "AGENT_CLAIMED", {}, stamp)
            return self._dict(db.execute(
                "SELECT * FROM agent_runs WHERE diagnosis_id=?", (row["diagnosis_id"],),
            ).fetchone())

    def renew_agent(self, diagnosis_id, lease_token, lease_seconds=30):
        db = self.connect()
        try:
            changed = db.execute(
                "UPDATE agent_runs SET lease_expires_at=?,updated_at=? WHERE diagnosis_id=? "
                "AND status='RUNNING' AND lease_token=?",
                (_deadline(lease_seconds), now(), diagnosis_id, lease_token),
            ).rowcount
            if changed != 1:
                raise LeaseLost("Agent lease is no longer owned by this worker")
        finally:
            db.close()

    def recover_expired_agents(self):
        stamp = now()
        with self.transaction() as db:
            rows = db.execute(
                "SELECT diagnosis_id FROM agent_runs WHERE status='RUNNING' "
                "AND lease_expires_at IS NOT NULL AND lease_expires_at<?", (stamp,),
            ).fetchall()
            for row in rows:
                ambiguous = db.execute(
                    "SELECT COUNT(*) FROM agent_tool_calls WHERE diagnosis_id=? "
                    "AND status='IN_FLIGHT'", (row["diagnosis_id"],),
                ).fetchone()[0]
                db.execute(
                    "UPDATE agent_runs SET status='QUEUED',lease_owner=NULL,lease_token=NULL,"
                    "lease_expires_at=NULL,updated_at=? WHERE diagnosis_id=?",
                    (stamp, row["diagnosis_id"]),
                )
                self._agent_audit(db, row["diagnosis_id"], "system", None,
                                  "AGENT_LEASE_RECOVERED", {"ambiguous_calls": ambiguous}, stamp)
            return len(rows)

    def yield_agent(self, diagnosis_id, lease_token, completed_node):
        stamp = now()
        with self.transaction() as db:
            changed = db.execute(
                "UPDATE agent_runs SET status='QUEUED',lease_owner=NULL,lease_token=NULL,"
                "lease_expires_at=NULL,updated_at=? WHERE diagnosis_id=? AND status='RUNNING' "
                "AND lease_token=?", (stamp, diagnosis_id, lease_token),
            ).rowcount
            if changed != 1:
                raise LeaseLost("Agent lease was lost before yielding the node")
            self._agent_audit(db, diagnosis_id, "worker", None, "AGENT_NODE_COMPLETED",
                              {"node": completed_node}, stamp)

    def update_agent_state(self, diagnosis_id, lease_token, current_node, state, budget):
        db = self.connect()
        try:
            changed = db.execute(
                "UPDATE agent_runs SET current_node=?,state_json=?,budget_json=?,updated_at=? "
                "WHERE diagnosis_id=? AND status='RUNNING' AND lease_token=?",
                (current_node, json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                 json.dumps(budget, separators=(",", ":")), now(), diagnosis_id, lease_token),
            ).rowcount
            if changed != 1:
                raise LeaseLost("Agent lease was lost while saving state")
        finally:
            db.close()

    def start_agent_tool(self, diagnosis_id, tool_name, args_hash, args, ordinal):
        stamp = now()
        tool_call_id = "tc_" + uuid.uuid4().hex[:24]
        with self.transaction() as db:
            found = db.execute(
                "SELECT * FROM agent_tool_calls WHERE diagnosis_id=? AND tool_name=? "
                "AND args_hash=?", (diagnosis_id, tool_name, args_hash),
            ).fetchone()
            if found:
                return self._dict(found), True
            db.execute(
                "INSERT INTO agent_tool_calls(tool_call_id,diagnosis_id,ordinal,tool_name,"
                "args_hash,args_json,status,started_at) VALUES (?,?,?,?,?,?,?,?)",
                (tool_call_id, diagnosis_id, ordinal, tool_name, args_hash,
                 json.dumps(args, ensure_ascii=False, separators=(",", ":")),
                 "IN_FLIGHT", stamp),
            )
            return self._dict(db.execute(
                "SELECT * FROM agent_tool_calls WHERE tool_call_id=?", (tool_call_id,),
            ).fetchone()), False

    def finish_agent_tool(self, tool_call_id, result, status="SUCCEEDED"):
        db = self.connect()
        try:
            db.execute(
                "UPDATE agent_tool_calls SET status=?,result_json=?,finished_at=? "
                "WHERE tool_call_id=? AND status='IN_FLIGHT'",
                (status, json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                 now(), tool_call_id),
            )
        finally:
            db.close()

    def save_agent_evidence(self, diagnosis_id, items):
        if not items:
            return
        with self.transaction() as db:
            db.executemany(
                "INSERT OR IGNORE INTO agent_evidence(evidence_id,diagnosis_id,kind,"
                "source_ref,version,observed_at,excerpt_redacted,evidence_hash) "
                "VALUES (?,?,?,?,?,?,?,?)",
                ((item["evidence_id"], diagnosis_id, item["kind"], item["source_ref"],
                  item["version"], item.get("observed_at"), item["excerpt_redacted"],
                  item["evidence_hash"]) for item in items),
            )

    def save_agent_report(self, diagnosis_id, lease_token, report, markdown, approval=None):
        stamp = now()
        payload = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM agent_runs WHERE diagnosis_id=? AND status='RUNNING' "
                "AND lease_token=?", (diagnosis_id, lease_token),
            ).fetchone()
            if not row:
                raise LeaseLost("Agent lease was lost before report publication")
            db.execute(
                "INSERT INTO incident_reports(report_id,diagnosis_id,revision,status,report_json,"
                "report_markdown,report_hash,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (report["report_id"], diagnosis_id, report["revision"],
                 report["diagnosis_status"], payload, markdown, report["report_hash"], stamp),
            )
            status = "WAITING_REVIEW" if approval else "COMPLETED"
            approval_id = None
            if approval:
                approval_id = approval["approval_id"]
                db.execute(
                    "INSERT INTO approvals(approval_id,diagnosis_id,report_id,report_hash,revision,"
                    "action_ids_json,status,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (approval_id, diagnosis_id, report["report_id"], report["report_hash"],
                     report["revision"], json.dumps(approval["action_ids"]), "PENDING",
                     stamp, approval["expires_at"]),
                )
            db.execute(
                "UPDATE agent_runs SET status=?,current_node='REPORT_VALIDATED',report_id=?,"
                "approval_id=?,finished_at=?,updated_at=?,lease_owner=NULL,lease_token=NULL,"
                "lease_expires_at=NULL WHERE diagnosis_id=?",
                (status, report["report_id"], approval_id, stamp, stamp, diagnosis_id),
            )
            self._agent_audit(db, diagnosis_id, "worker", row["lease_owner"],
                              "AGENT_REPORT_PUBLISHED", {"status": status,
                              "report_id": report["report_id"]}, stamp)
        return self.one("SELECT * FROM agent_runs WHERE diagnosis_id=?", (diagnosis_id,))

    def fail_agent(self, diagnosis_id, lease_token, code, message):
        stamp = now()
        with self.transaction() as db:
            changed = db.execute(
                "UPDATE agent_runs SET status='FAILED',error_code=?,error_message=?,"
                "finished_at=?,updated_at=?,lease_owner=NULL,lease_token=NULL,"
                "lease_expires_at=NULL WHERE diagnosis_id=? AND status='RUNNING' "
                "AND lease_token=?", (code, str(message)[:2000], stamp, stamp,
                                      diagnosis_id, lease_token),
            ).rowcount
            if changed != 1:
                raise LeaseLost("Agent lease was lost before failure could be recorded")
            self._agent_audit(db, diagnosis_id, "worker", None, "AGENT_FAILED",
                              {"code": code}, stamp)

    def get_agent_run(self, diagnosis_id):
        row = self.one("SELECT * FROM agent_runs WHERE diagnosis_id=?", (diagnosis_id,))
        if row:
            row["state"] = json.loads(row.pop("state_json"))
            row["budget"] = json.loads(row.pop("budget_json"))
        return row

    def expire_approvals(self):
        stamp = now()
        with self.transaction() as db:
            rows = db.execute(
                "SELECT approval_id,diagnosis_id FROM approvals WHERE status='PENDING' "
                "AND expires_at<?", (stamp,),
            ).fetchall()
            for row in rows:
                db.execute("UPDATE approvals SET status='EXPIRED',decided_at=? WHERE approval_id=?",
                           (stamp, row["approval_id"]))
                db.execute("UPDATE agent_runs SET status='EXPIRED',updated_at=? WHERE diagnosis_id=? "
                           "AND status='WAITING_REVIEW'", (stamp, row["diagnosis_id"]))
            return len(rows)

    def decide_approval(self, approval_id, decision, report_hash, revision, reason,
                        reviewer_id, idempotency_key):
        self.expire_approvals()
        stamp = now()
        target = {"approve": "APPROVED", "reject": "REJECTED",
                  "request_more_evidence": "NEEDS_MORE_EVIDENCE"}[decision]
        with self.transaction() as db:
            same_key = db.execute(
                "SELECT * FROM approvals WHERE idempotency_key=?", (idempotency_key,),
            ).fetchone()
            if same_key:
                same_request = (
                    same_key["approval_id"] == approval_id
                    and same_key["status"] == target
                    and same_key["report_hash"] == report_hash
                    and int(same_key["revision"]) == int(revision)
                    and same_key["reason"] == reason
                    and same_key["reviewer_id"] == reviewer_id
                )
                if not same_request:
                    raise ApprovalConflict("Idempotency-Key was used for another decision")
                return self._dict(same_key), None
            row = db.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
            if not row:
                raise FileNotFoundError("Approval was not found")
            if row["status"] == "EXPIRED":
                raise ApprovalExpired("Approval has expired")
            if row["expires_at"] < stamp:
                raise ApprovalExpired("Approval has expired")
            if row["status"] != "PENDING":
                raise ApprovalConflict("Approval has already been decided")
            if row["report_hash"] != report_hash or int(row["revision"]) != int(revision):
                raise ApprovalConflict("Approval report version does not match")
            db.execute(
                "UPDATE approvals SET status=?,reviewer_id=?,reason=?,decided_at=?,"
                "idempotency_key=? WHERE approval_id=? AND status='PENDING'",
                (target, reviewer_id, reason, stamp, idempotency_key, approval_id),
            )
            next_run = None
            if decision == "request_more_evidence":
                parent = db.execute("SELECT * FROM agent_runs WHERE diagnosis_id=?",
                                    (row["diagnosis_id"],)).fetchone()
                if int(parent["revision"]) >= 2:
                    raise ApprovalConflict("Only one evidence revision is allowed")
                next_id = "dia_" + uuid.uuid4().hex[:24]
                next_budget = json.loads(parent["budget_json"])
                for name in ("tool_calls", "llm_calls", "tokens", "active_ms",
                             "estimated_cost_cny"):
                    next_budget[name] = 0
                state = {"tool_calls": [], "evidence_ids": [], "errors": [],
                         "review_reasons": ["reviewer_requested_more_evidence"],
                         "reviewer_reason": reason}
                fingerprint = parent["request_fingerprint"] + ":revision:2"
                db.execute(
                    "INSERT INTO agent_runs(diagnosis_id,event_id,revision,parent_diagnosis_id,"
                    "mode,status,current_node,state_json,budget_json,release_id,request_fingerprint,"
                    "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (next_id, parent["event_id"], 2, parent["diagnosis_id"], parent["mode"],
                     "QUEUED", "RECEIVED", json.dumps(state, ensure_ascii=False),
                     json.dumps(next_budget), parent["release_id"], fingerprint, stamp, stamp),
                )
                next_run = next_id
                db.execute("UPDATE agent_runs SET status='NEEDS_MORE_EVIDENCE',updated_at=? "
                           "WHERE diagnosis_id=?", (stamp, parent["diagnosis_id"]))
            else:
                run_status = "APPROVED_REPORT" if decision == "approve" else "REJECTED"
                db.execute("UPDATE agent_runs SET status=?,updated_at=? WHERE diagnosis_id=?",
                           (run_status, stamp, row["diagnosis_id"]))
            self._agent_audit(db, row["diagnosis_id"], "reviewer", reviewer_id,
                              "APPROVAL_DECIDED", {"decision": decision,
                              "next_diagnosis_id": next_run}, stamp)
            return self._dict(db.execute(
                "SELECT * FROM approvals WHERE approval_id=?", (approval_id,),
            ).fetchone()), next_run

    def import_provider_usage(self, provider, legacy):
        stamp = now()
        with self.transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO provider_usage(provider,updated_at) VALUES (?,?)",
                (provider, stamp),
            )
            row = db.execute("SELECT imported_legacy FROM provider_usage WHERE provider=?",
                             (provider,)).fetchone()
            if not row["imported_legacy"]:
                db.execute(
                    "UPDATE provider_usage SET input_tokens=?,output_tokens=?,"
                    "estimated_cost_cny=?,calls=?,imported_legacy=1,updated_at=? WHERE provider=?",
                    (int(legacy.get("input_tokens", 0)), int(legacy.get("output_tokens", 0)),
                     float(legacy.get("estimated_cost_cny", 0)), int(legacy.get("calls", 0)),
                     stamp, provider),
                )

    def reserve_provider_usage(self, provider, scope, reserved_tokens, reserved_cost,
                               max_tokens, max_cost):
        stamp = now()
        reservation_id = "res_" + uuid.uuid4().hex[:24]
        with self.transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO provider_usage(provider,updated_at) VALUES (?,?)",
                (provider, stamp),
            )
            usage = db.execute("SELECT * FROM provider_usage WHERE provider=?",
                               (provider,)).fetchone()
            pending = db.execute(
                "SELECT COALESCE(SUM(reserved_tokens),0),COALESCE(SUM(reserved_cost_cny),0) "
                "FROM provider_reservations WHERE provider=? AND status='RESERVED'",
                (provider,),
            ).fetchone()
            used_tokens = usage["input_tokens"] + usage["output_tokens"] + pending[0]
            used_cost = usage["estimated_cost_cny"] + pending[1]
            if used_tokens + int(reserved_tokens) > int(max_tokens):
                raise RuntimeError("Token budget has been exhausted")
            if used_cost + float(reserved_cost) > float(max_cost):
                raise RuntimeError("Cost budget has been exhausted")
            db.execute(
                "INSERT INTO provider_reservations VALUES (?,?,?,?,?,'RESERVED',?,NULL)",
                (reservation_id, provider, scope, int(reserved_tokens),
                 float(reserved_cost), stamp),
            )
        return reservation_id

    def settle_provider_usage(self, reservation_id, input_tokens, output_tokens,
                              input_rate, output_rate):
        stamp = now()
        cost = (int(input_tokens) * float(input_rate)
                + int(output_tokens) * float(output_rate)) / 1_000_000
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM provider_reservations WHERE reservation_id=? AND status='RESERVED'",
                (reservation_id,),
            ).fetchone()
            if not row:
                raise ValueError("Provider budget reservation is unavailable")
            db.execute(
                "UPDATE provider_usage SET input_tokens=input_tokens+?,"
                "output_tokens=output_tokens+?,estimated_cost_cny=estimated_cost_cny+?,"
                "calls=calls+1,updated_at=? WHERE provider=?",
                (int(input_tokens), int(output_tokens), cost, stamp, row["provider"]),
            )
            db.execute(
                "UPDATE provider_reservations SET status='SETTLED',settled_at=? "
                "WHERE reservation_id=?", (stamp, reservation_id),
            )
        return self.provider_usage(row["provider"])

    def settle_provider_reservations_conservatively(self, provider, scope,
                                                    reservation_id=None):
        """Close ambiguous paid calls without allowing their reservation to disappear."""
        stamp = now()
        with self.transaction() as db:
            params = [provider, scope]
            clause = "provider=? AND scope=? AND status='RESERVED'"
            if reservation_id:
                clause += " AND reservation_id=?"
                params.append(reservation_id)
            rows = db.execute(
                f"SELECT * FROM provider_reservations WHERE {clause}", params).fetchall()
            if not rows:
                return 0
            tokens = sum(int(row["reserved_tokens"]) for row in rows)
            cost = sum(float(row["reserved_cost_cny"]) for row in rows)
            db.execute(
                "UPDATE provider_usage SET input_tokens=input_tokens+?,"
                "estimated_cost_cny=estimated_cost_cny+?,calls=calls+?,updated_at=? "
                "WHERE provider=?", (tokens, cost, len(rows), stamp, provider))
            ids = [row["reservation_id"] for row in rows]
            db.executemany(
                "UPDATE provider_reservations SET status='CONSERVATIVE',settled_at=? "
                "WHERE reservation_id=?", [(stamp, value) for value in ids])
        return len(rows)

    def provider_usage(self, provider):
        row = self.one("SELECT * FROM provider_usage WHERE provider=?", (provider,))
        if not row:
            return {"schema_version": 2, "input_tokens": 0, "output_tokens": 0,
                    "estimated_cost_cny": 0.0, "calls": 0, "reserved_tokens": 0}
        pending = self.one(
            "SELECT COALESCE(SUM(reserved_tokens),0) AS tokens FROM provider_reservations "
            "WHERE provider=? AND status='RESERVED'", (provider,),
        )
        return {"schema_version": 2, "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "estimated_cost_cny": row["estimated_cost_cny"], "calls": row["calls"],
                "reserved_tokens": pending["tokens"]}

    def one(self, query, params=()):
        db = self.connect()
        try:
            return self._dict(db.execute(query, params).fetchone())
        finally:
            db.close()

    def all(self, query, params=()):
        db = self.connect()
        try:
            return [dict(row) for row in db.execute(query, params).fetchall()]
        finally:
            db.close()
