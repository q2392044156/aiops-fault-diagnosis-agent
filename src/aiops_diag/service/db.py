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
"""


class IdempotencyConflict(ValueError):
    pass


class QueueFull(RuntimeError):
    pass


class LeaseLost(RuntimeError):
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
            task_columns = {row[1] for row in db.execute("PRAGMA table_info(tasks)")}
            for name in ("lease_owner", "lease_token", "lease_expires_at"):
                if name not in task_columns:
                    db.execute(f"ALTER TABLE tasks ADD COLUMN {name} TEXT")
            rows = db.execute("SELECT version FROM schema_meta").fetchall()
            if not rows:
                db.execute("INSERT INTO schema_meta(version) VALUES (2)")
            elif len(rows) != 1 or rows[0][0] not in (1, 2):
                raise ValueError("Unsupported service database schema")
            else:
                db.execute("UPDATE schema_meta SET version=2")
        finally:
            db.close()

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
