from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorBody(StrictModel):
    schema_version: int = 1
    code: str
    message: str
    retryable: bool = False
    request_id: str


class RegisteredRequest(StrictModel):
    registered_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")


class TaskResponse(StrictModel):
    schema_version: int = 1
    task_id: str
    batch_id: str
    status: str
    stage: str
    attempts: int
    error: dict[str, Any] | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    deduplicated: bool = False
    links: dict[str, str]


class BatchResponse(StrictModel):
    schema_version: int = 1
    batch_id: str
    source_kind: str
    input_hash: str
    release_id: str
    status: str
    counts: dict[str, int]
    created_at: str
    updated_at: str


class EventItem(StrictModel):
    event_id: str
    batch_id: str
    host_alias: str | None
    start_time: str | None
    end_time: str | None
    detected_at: str
    max_anomaly_score: float
    threshold: float
    session_count: int
    status: str


class EventList(StrictModel):
    schema_version: int = 1
    items: list[EventItem]
    next_cursor: str | None


class SessionItem(StrictModel):
    batch_id: str
    session_id: str
    start_time: str | None
    end_time: str | None
    line_count: int
    unknown_count: int
    anomaly_score: float
    threshold: float
    prediction: int
    first_log_id: str | None
    last_log_id: str | None
    host_alias: str | None


class EventDetail(StrictModel):
    schema_version: int = 1
    event: EventItem
    sessions: list[SessionItem]


class SessionResponse(SessionItem):
    schema_version: int = 1


class LogItem(StrictModel):
    log_id: str
    raw_line_no: int
    timestamp: str | None
    level: str | None
    component: str | None
    redacted_message: str
    template_id: int | None
    session_ids: list[str]
    parse_status: str


class LogList(StrictModel):
    schema_version: int = 1
    items: list[LogItem]
    next_cursor: str | None


class HealthResponse(StrictModel):
    schema_version: int = 1
    status: str
    detail: str | None = None


class ReleaseResponse(StrictModel):
    schema_version: int
    release_id: str
    model_id: str
    model_family: str
    threshold: float
    anomaly_score_semantics: str
    protocol_hash: str
    template_manifest_hash: str
