from typing import Any, Literal

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


class RegisteredBatchList(StrictModel):
    schema_version: int = 1
    items: list[str]


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
    deployment_release: str | None = None
    release_id: str
    model_id: str
    model_family: str
    threshold: float
    anomaly_score_semantics: str
    protocol_hash: str
    template_manifest_hash: str


class OperationsSummary(StrictModel):
    schema_version: int = 1
    release_id: str
    worker_ready: bool
    worker_heartbeat_at: str | None
    queued: int
    running: int
    succeeded: int
    failed: int
    oldest_queue_seconds: float | None
    last_finished_at: str | None


class RetrievalSearchRequest(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int | None = Field(default=None, ge=1, le=10)
    mode: Literal["frozen", "bm25", "dense", "hybrid"] = "frozen"
    component: str | None = Field(default=None, min_length=1, max_length=64)
    product_version: str | None = Field(default=None, min_length=1, max_length=32)


class RetrievalItem(StrictModel):
    rank: int
    chunk_id: str
    doc_id: str
    title: str
    section_path: str
    excerpt: str
    component: list[str]
    product: str
    version_scope: list[str]
    risk_level: str
    source_id: str
    source_url: str | None
    source_version: str
    maintained_at: str
    evidence_url: str
    bm25_score: float
    dense_score: float | None
    rrf_score: float


class RetrievalSearchResponse(StrictModel):
    schema_version: int = 1
    kb_release_id: str
    mode: str
    status: Literal["evidence_found", "insufficient_evidence"]
    elapsed_ms: float
    items: list[RetrievalItem]


class KnowledgeChunkResponse(StrictModel):
    schema_version: int = 1
    kb_release_id: str
    chunk_id: str
    doc_id: str
    title: str
    section_path: str
    text: str
    component: list[str]
    product: str
    version_scope: list[str]
    risk_level: str
    source_id: str
    source_url: str | None
    source_version: str
    maintained_at: str


class KnowledgeReleaseResponse(StrictModel):
    schema_version: int
    kb_release_id: str
    corpus_hash: str
    index_hash: str
    model_revision: str
    model_hash: str
    default_mode: str
    default_k: int
    gate_threshold: float
    chunk_variant: str
    chunk_count: int


class RagReportRequest(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    component: str | None = Field(default=None, min_length=1, max_length=64)
    product_version: str | None = Field(default=None, min_length=1, max_length=32)
    mode: Literal["auto", "template"] = "auto"


class RagReleaseResponse(StrictModel):
    schema_version: int
    rag_version: str
    kb_release_id: str
    provider: str
    model: str
    prompt_version: str
    prompt_hash: str
    config_hash: str
    online_configured: bool
    reranker_enabled: bool
