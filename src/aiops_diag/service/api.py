import base64
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import pyarrow.parquet as pq
from fastapi import FastAPI, File, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .db import IdempotencyConflict
from .runtime import ServiceRuntime
from .schemas import (BatchResponse, ErrorBody, EventDetail, EventList, HealthResponse,
                      LogItem, LogList, RegisteredRequest, ReleaseResponse, SessionResponse,
                      TaskResponse)


class ServiceError(Exception):
    def __init__(self, status, code, message, retryable=False):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable


def _encode_cursor(value):
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value):
    if not value:
        return None
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except Exception as exc:
        raise ServiceError(422, "INVALID_CURSOR", "Cursor is invalid") from exc


def _time_bound(value):
    if value is None:
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ServiceError(422, "INVALID_TIME_RANGE", "Time bounds must be ISO-8601") from exc
    if stamp.tzinfo is not None:
        raise ServiceError(422, "INVALID_TIME_RANGE",
                           "HDFS timestamps have unknown timezone; use a timezone-free bound")
    return stamp.isoformat()


def _task(row, deduplicated=False):
    if not row:
        raise ServiceError(404, "TASK_NOT_FOUND", "Task was not found")
    return {
        "task_id": row["task_id"], "batch_id": row["batch_id"], "status": row["status"],
        "stage": row["stage"], "attempts": row["attempts"],
        "error": ({"code": row["error_code"], "message": row["error_message"]}
                  if row.get("error_code") else None),
        "created_at": row["created_at"], "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"), "deduplicated": deduplicated,
        "links": {"self": f"/api/v1/tasks/{row['task_id']}",
                  "batch": f"/api/v1/batches/{row['batch_id']}"},
    }


def create_app(cfg, start_worker=True, runtime=None):
    runtime = runtime or ServiceRuntime(cfg)

    @asynccontextmanager
    async def lifespan(_app):
        if start_worker:
            runtime.start()
        yield
        runtime.stop()

    app = FastAPI(title="AIOps Fault Diagnosis API", version="0.3.0-w5", lifespan=lifespan)
    app.state.runtime = runtime

    @app.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(ServiceError)
    async def service_error(request, exc):
        body = ErrorBody(code=exc.code, message=exc.message, retryable=exc.retryable,
                         request_id=getattr(request.state, "request_id", uuid.uuid4().hex))
        return JSONResponse(status_code=exc.status, content=body.model_dump())

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        body = ErrorBody(code="VALIDATION_ERROR", message=str(exc.errors()),
                         request_id=getattr(request.state, "request_id", uuid.uuid4().hex))
        return JSONResponse(status_code=422, content=body.model_dump())

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        body = ErrorBody(code="INTERNAL_ERROR", message="Internal service error", retryable=True,
                         request_id=getattr(request.state, "request_id", uuid.uuid4().hex))
        return JSONResponse(status_code=500, content=body.model_dump())

    @app.get("/api/v1/health/live", response_model=HealthResponse)
    def live():
        return {"status": "live"}

    @app.get("/api/v1/health/ready", response_model=HealthResponse,
             responses={503: {"model": ErrorBody}})
    def ready():
        if not runtime.ready:
            raise ServiceError(503, "MODEL_UNAVAILABLE", runtime.ready_error or "Not ready", True)
        return {"status": "ready"}

    @app.get("/api/v1/releases/current", response_model=ReleaseResponse)
    def current_release():
        if not runtime.ready:
            raise ServiceError(503, "MODEL_UNAVAILABLE", runtime.ready_error or "Not ready", True)
        return runtime.model.public()

    @app.post("/api/v1/batches/uploads", status_code=202, response_model=TaskResponse)
    async def upload_batch(file: UploadFile = File(...), idempotency_key: str | None = Header(
            default=None, alias="Idempotency-Key")):
        try:
            row, duplicate = await runtime.submit_upload(file, idempotency_key)
            return _task(row, duplicate)
        except OverflowError as exc:
            raise ServiceError(413, "UPLOAD_TOO_LARGE", str(exc)) from exc
        except EOFError as exc:
            raise ServiceError(422, "EMPTY_UPLOAD", str(exc)) from exc
        except TypeError as exc:
            raise ServiceError(415, "UNSUPPORTED_MEDIA", str(exc)) from exc
        except IdempotencyConflict as exc:
            raise ServiceError(409, "IDEMPOTENCY_CONFLICT", str(exc)) from exc
        except ValueError as exc:
            raise ServiceError(422, "INVALID_REQUEST", str(exc)) from exc
        except RuntimeError as exc:
            raise ServiceError(503, "MODEL_UNAVAILABLE", str(exc), True) from exc

    @app.post("/api/v1/batches/registered", status_code=202, response_model=TaskResponse)
    def registered_batch(body: RegisteredRequest, idempotency_key: str | None = Header(
            default=None, alias="Idempotency-Key")):
        try:
            row, duplicate = runtime.submit_registered(body.registered_id, idempotency_key)
            return _task(row, duplicate)
        except FileNotFoundError as exc:
            raise ServiceError(404, "REGISTERED_SOURCE_NOT_FOUND", str(exc)) from exc
        except IdempotencyConflict as exc:
            raise ServiceError(409, "IDEMPOTENCY_CONFLICT", str(exc)) from exc
        except ValueError as exc:
            raise ServiceError(422, "INVALID_REQUEST", str(exc)) from exc
        except RuntimeError as exc:
            raise ServiceError(503, "MODEL_UNAVAILABLE", str(exc), True) from exc

    @app.get("/api/v1/tasks/{task_id}", response_model=TaskResponse)
    def task_status(task_id: str):
        row = runtime.db.one("SELECT * FROM tasks WHERE task_id=?", (task_id,))
        return _task(row)

    @app.get("/api/v1/batches/{batch_id}", response_model=BatchResponse)
    def batch_status(batch_id: str):
        row = runtime.db.one("SELECT * FROM batches WHERE batch_id=?", (batch_id,))
        if not row:
            raise ServiceError(404, "BATCH_NOT_FOUND", "Batch was not found")
        return {
            "batch_id": row["batch_id"], "source_kind": row["source_kind"],
            "input_hash": row["input_hash"], "release_id": row["release_id"],
            "status": row["status"], "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "counts": {name: row[name] for name in ("total_lines", "parsed_lines",
                       "quarantined_lines", "session_count", "anomaly_count", "event_count")},
        }

    @app.get("/api/v1/events", response_model=EventList)
    def events(batch_id: str | None = None, limit: int = Query(50, ge=1, le=200),
               cursor: str | None = None):
        position = _decode_cursor(cursor)
        clauses, params = [], []
        if batch_id:
            clauses.append("batch_id=?"); params.append(batch_id)
        if position:
            if set(position) != {"start_time", "event_id"}:
                raise ServiceError(422, "INVALID_CURSOR", "Cursor fields are invalid")
            if not isinstance(position["start_time"], str) or not isinstance(position["event_id"], str):
                raise ServiceError(422, "INVALID_CURSOR", "Cursor values are invalid")
            clauses.append("(COALESCE(start_time,'') > ? OR (COALESCE(start_time,'')=? AND event_id>?))")
            params.extend([position["start_time"], position["start_time"], position["event_id"]])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = runtime.db.all("SELECT * FROM events" + where +
                              " ORDER BY COALESCE(start_time,''),event_id LIMIT ?", (*params, limit + 1))
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (_encode_cursor({"start_time": rows[-1]["start_time"] or "",
                                       "event_id": rows[-1]["event_id"]}) if more else None)
        return {"items": rows, "next_cursor": next_cursor}

    @app.get("/api/v1/events/{event_id}", response_model=EventDetail)
    def event_detail(event_id: str):
        event = runtime.db.one("SELECT * FROM events WHERE event_id=?", (event_id,))
        if not event:
            raise ServiceError(404, "EVENT_NOT_FOUND", "Event was not found")
        sessions = runtime.db.all(
            "SELECT s.* FROM sessions s JOIN event_sessions e ON e.batch_id=s.batch_id "
            "AND e.session_id=s.session_id WHERE e.event_id=? ORDER BY s.session_id", (event_id,))
        return {"event": event, "sessions": sessions}

    @app.get("/api/v1/batches/{batch_id}/sessions/{session_id}", response_model=SessionResponse)
    def session_detail(batch_id: str, session_id: str):
        row = runtime.db.one("SELECT * FROM sessions WHERE batch_id=? AND session_id=?",
                             (batch_id, session_id))
        if not row:
            raise ServiceError(404, "SESSION_NOT_FOUND", "Session was not found")
        return row

    def batch_artifact_dir(batch_id):
        row = runtime.db.one("SELECT status,artifact_dir FROM batches WHERE batch_id=?", (batch_id,))
        if not row:
            raise ServiceError(404, "BATCH_NOT_FOUND", "Batch was not found")
        if row["status"] != "SUCCEEDED" or not row["artifact_dir"]:
            raise ServiceError(409, "BATCH_NOT_READY", "Batch processing has not completed", True)
        directory = Path(row["artifact_dir"]).resolve()
        root = (Path(cfg["paths"]["runtime_dir"]) / "batches").resolve()
        if directory.parent != root:
            raise ServiceError(500, "ARTIFACT_PATH_INVALID", "Stored artifact path is invalid")
        return directory

    def scan_logs(batch_id, session_id=None, start=None, end=None, after=0, limit=50,
                  exact_log_id=None):
        directory = batch_artifact_dir(batch_id)
        found = []
        for batch in pq.ParquetFile(directory / "logs.parquet").iter_batches(batch_size=10000):
            for row in batch.to_pylist():
                if row["raw_line_no"] <= after:
                    continue
                if exact_log_id is not None and row["log_id"] != exact_log_id:
                    continue
                if session_id is not None and session_id not in row["session_ids"]:
                    continue
                if start is not None and (row["timestamp"] is None or row["timestamp"] < start):
                    continue
                if end is not None and (row["timestamp"] is None or row["timestamp"] >= end):
                    continue
                found.append(row)
                if len(found) >= limit + 1:
                    return found
        return found

    @app.get("/api/v1/batches/{batch_id}/logs", response_model=LogList)
    def logs(batch_id: str, session_id: str | None = None, start: str | None = None,
             end: str | None = None, limit: int = Query(50, ge=1, le=200),
             cursor: str | None = None):
        if session_id is None and start is None and end is None:
            raise ServiceError(422, "LOG_FILTER_REQUIRED", "Provide session_id or a time range")
        start = _time_bound(start)
        end = _time_bound(end)
        if start is not None and end is not None and start >= end:
            raise ServiceError(422, "INVALID_TIME_RANGE", "start must be earlier than end")
        position = _decode_cursor(cursor)
        if position and set(position) != {"raw_line_no"}:
            raise ServiceError(422, "INVALID_CURSOR", "Cursor fields are invalid")
        try:
            after = int(position["raw_line_no"]) if position else 0
        except (TypeError, ValueError) as exc:
            raise ServiceError(422, "INVALID_CURSOR", "Cursor values are invalid") from exc
        if after < 0:
            raise ServiceError(422, "INVALID_CURSOR", "Cursor values are invalid")
        rows = scan_logs(batch_id, session_id, start, end, after, limit)
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = _encode_cursor({"raw_line_no": rows[-1]["raw_line_no"]}) if more else None
        return {"items": rows, "next_cursor": next_cursor}

    @app.get("/api/v1/batches/{batch_id}/logs/{log_id}", response_model=LogItem)
    def log_detail(batch_id: str, log_id: str):
        rows = scan_logs(batch_id, exact_log_id=log_id, limit=1)
        if not rows:
            raise ServiceError(404, "LOG_NOT_FOUND", "Log was not found")
        return rows[0]

    return app
