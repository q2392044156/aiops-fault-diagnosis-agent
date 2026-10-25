"""模块说明：定义当前模块输入输出的 Pydantic 数据结构。"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# 类说明：`StrictModel` 封装本模块内聚的数据和行为。
class StrictModel(BaseModel):
    # 变量说明：`model_config` 保存本模块或数据模型使用的稳定值。
    model_config = ConfigDict(extra="forbid")


# 类说明：`ErrorBody` 封装本模块内聚的数据和行为。
class ErrorBody(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int = 1
    # 变量说明：`code` 保存本模块或数据模型使用的稳定值。
    code: str
    # 变量说明：`message` 保存本模块或数据模型使用的稳定值。
    message: str
    # 变量说明：`retryable` 保存本模块或数据模型使用的稳定值。
    retryable: bool = False
    # 变量说明：`request_id` 保存本模块或数据模型使用的稳定值。
    request_id: str


# 类说明：`RegisteredRequest` 封装本模块内聚的数据和行为。
class RegisteredRequest(StrictModel):
    # 变量说明：`registered_id` 保存本模块或数据模型使用的稳定值。
    registered_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")


# 类说明：`RegisteredBatchList` 封装本模块内聚的数据和行为。
class RegisteredBatchList(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int = 1
    # 变量说明：`items` 保存本模块或数据模型使用的稳定值。
    items: list[str]


# 类说明：`TaskResponse` 封装本模块内聚的数据和行为。
class TaskResponse(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int = 1
    # 变量说明：`task_id` 保存本模块或数据模型使用的稳定值。
    task_id: str
    # 变量说明：`batch_id` 保存本模块或数据模型使用的稳定值。
    batch_id: str
    # 变量说明：`status` 保存本模块或数据模型使用的稳定值。
    status: str
    # 变量说明：`stage` 保存本模块或数据模型使用的稳定值。
    stage: str
    # 变量说明：`attempts` 保存本模块或数据模型使用的稳定值。
    attempts: int
    # 变量说明：`error` 保存本模块或数据模型使用的稳定值。
    error: dict[str, Any] | None = None
    # 变量说明：`created_at` 保存本模块或数据模型使用的稳定值。
    created_at: str
    # 变量说明：`started_at` 保存本模块或数据模型使用的稳定值。
    started_at: str | None = None
    # 变量说明：`finished_at` 保存本模块或数据模型使用的稳定值。
    finished_at: str | None = None
    # 变量说明：`deduplicated` 保存本模块或数据模型使用的稳定值。
    deduplicated: bool = False
    # 变量说明：`links` 保存本模块或数据模型使用的稳定值。
    links: dict[str, str]


# 类说明：`BatchResponse` 封装本模块内聚的数据和行为。
class BatchResponse(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int = 1
    # 变量说明：`batch_id` 保存本模块或数据模型使用的稳定值。
    batch_id: str
    # 变量说明：`source_kind` 保存本模块或数据模型使用的稳定值。
    source_kind: str
    # 变量说明：`input_hash` 保存本模块或数据模型使用的稳定值。
    input_hash: str
    # 变量说明：`release_id` 保存本模块或数据模型使用的稳定值。
    release_id: str
    # 变量说明：`status` 保存本模块或数据模型使用的稳定值。
    status: str
    # 变量说明：`counts` 保存本模块或数据模型使用的稳定值。
    counts: dict[str, int]
    # 变量说明：`created_at` 保存本模块或数据模型使用的稳定值。
    created_at: str
    # 变量说明：`updated_at` 保存本模块或数据模型使用的稳定值。
    updated_at: str


# 类说明：`EventItem` 封装本模块内聚的数据和行为。
class EventItem(StrictModel):
    # 变量说明：`event_id` 保存本模块或数据模型使用的稳定值。
    event_id: str
    # 变量说明：`batch_id` 保存本模块或数据模型使用的稳定值。
    batch_id: str
    # 变量说明：`host_alias` 保存本模块或数据模型使用的稳定值。
    host_alias: str | None
    # 变量说明：`start_time` 保存本模块或数据模型使用的稳定值。
    start_time: str | None
    # 变量说明：`end_time` 保存本模块或数据模型使用的稳定值。
    end_time: str | None
    # 变量说明：`detected_at` 保存本模块或数据模型使用的稳定值。
    detected_at: str
    # 变量说明：`max_anomaly_score` 保存本模块或数据模型使用的稳定值。
    max_anomaly_score: float
    # 变量说明：`threshold` 保存本模块或数据模型使用的稳定值。
    threshold: float
    # 变量说明：`session_count` 保存本模块或数据模型使用的稳定值。
    session_count: int
    # 变量说明：`status` 保存本模块或数据模型使用的稳定值。
    status: str


# 类说明：`EventList` 封装本模块内聚的数据和行为。
class EventList(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int = 1
    # 变量说明：`items` 保存本模块或数据模型使用的稳定值。
    items: list[EventItem]
    # 变量说明：`next_cursor` 保存本模块或数据模型使用的稳定值。
    next_cursor: str | None


# 类说明：`SessionItem` 封装本模块内聚的数据和行为。
class SessionItem(StrictModel):
    # 变量说明：`batch_id` 保存本模块或数据模型使用的稳定值。
    batch_id: str
    # 变量说明：`session_id` 保存本模块或数据模型使用的稳定值。
    session_id: str
    # 变量说明：`start_time` 保存本模块或数据模型使用的稳定值。
    start_time: str | None
    # 变量说明：`end_time` 保存本模块或数据模型使用的稳定值。
    end_time: str | None
    # 变量说明：`line_count` 保存本模块或数据模型使用的稳定值。
    line_count: int
    # 变量说明：`unknown_count` 保存本模块或数据模型使用的稳定值。
    unknown_count: int
    # 变量说明：`anomaly_score` 保存本模块或数据模型使用的稳定值。
    anomaly_score: float
    # 变量说明：`threshold` 保存本模块或数据模型使用的稳定值。
    threshold: float
    # 变量说明：`prediction` 保存本模块或数据模型使用的稳定值。
    prediction: int
    # 变量说明：`first_log_id` 保存本模块或数据模型使用的稳定值。
    first_log_id: str | None
    # 变量说明：`last_log_id` 保存本模块或数据模型使用的稳定值。
    last_log_id: str | None
    # 变量说明：`host_alias` 保存本模块或数据模型使用的稳定值。
    host_alias: str | None


# 类说明：`EventDetail` 封装本模块内聚的数据和行为。
class EventDetail(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int = 1
    # 变量说明：`event` 保存本模块或数据模型使用的稳定值。
    event: EventItem
    # 变量说明：`sessions` 保存本模块或数据模型使用的稳定值。
    sessions: list[SessionItem]


# 类说明：`SessionResponse` 封装本模块内聚的数据和行为。
class SessionResponse(SessionItem):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int = 1


# 类说明：`LogItem` 封装本模块内聚的数据和行为。
class LogItem(StrictModel):
    # 变量说明：`log_id` 保存本模块或数据模型使用的稳定值。
    log_id: str
    # 变量说明：`raw_line_no` 保存本模块或数据模型使用的稳定值。
    raw_line_no: int
    # 变量说明：`timestamp` 保存本模块或数据模型使用的稳定值。
    timestamp: str | None
    # 变量说明：`level` 保存本模块或数据模型使用的稳定值。
    level: str | None
    # 变量说明：`component` 保存本模块或数据模型使用的稳定值。
    component: str | None
    # 变量说明：`redacted_message` 保存本模块或数据模型使用的稳定值。
    redacted_message: str
    # 变量说明：`template_id` 保存本模块或数据模型使用的稳定值。
    template_id: int | None
    # 变量说明：`session_ids` 保存本模块或数据模型使用的稳定值。
    session_ids: list[str]
    # 变量说明：`parse_status` 保存本模块或数据模型使用的稳定值。
    parse_status: str


# 类说明：`LogList` 封装本模块内聚的数据和行为。
class LogList(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int = 1
    # 变量说明：`items` 保存本模块或数据模型使用的稳定值。
    items: list[LogItem]
    # 变量说明：`next_cursor` 保存本模块或数据模型使用的稳定值。
    next_cursor: str | None


# 类说明：`HealthResponse` 封装本模块内聚的数据和行为。
class HealthResponse(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int = 1
    # 变量说明：`status` 保存本模块或数据模型使用的稳定值。
    status: str
    # 变量说明：`detail` 保存本模块或数据模型使用的稳定值。
    detail: str | None = None


# 类说明：`ReleaseResponse` 封装本模块内聚的数据和行为。
class ReleaseResponse(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int
    # 变量说明：`deployment_release` 保存本模块或数据模型使用的稳定值。
    deployment_release: str | None = None
    # 变量说明：`release_id` 保存本模块或数据模型使用的稳定值。
    release_id: str
    # 变量说明：`model_id` 保存本模块或数据模型使用的稳定值。
    model_id: str
    # 变量说明：`model_family` 保存本模块或数据模型使用的稳定值。
    model_family: str
    # 变量说明：`threshold` 保存本模块或数据模型使用的稳定值。
    threshold: float
    # 变量说明：`anomaly_score_semantics` 保存本模块或数据模型使用的稳定值。
    anomaly_score_semantics: str
    # 变量说明：`protocol_hash` 保存本模块或数据模型使用的稳定值。
    protocol_hash: str
    # 变量说明：`template_manifest_hash` 保存本模块或数据模型使用的稳定值。
    template_manifest_hash: str


# 类说明：`OperationsSummary` 封装本模块内聚的数据和行为。
class OperationsSummary(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int = 1
    # 变量说明：`release_id` 保存本模块或数据模型使用的稳定值。
    release_id: str
    # 变量说明：`worker_ready` 保存本模块或数据模型使用的稳定值。
    worker_ready: bool
    # 变量说明：`worker_heartbeat_at` 保存本模块或数据模型使用的稳定值。
    worker_heartbeat_at: str | None
    # 变量说明：`queued` 保存本模块或数据模型使用的稳定值。
    queued: int
    # 变量说明：`running` 保存本模块或数据模型使用的稳定值。
    running: int
    # 变量说明：`succeeded` 保存本模块或数据模型使用的稳定值。
    succeeded: int
    # 变量说明：`failed` 保存本模块或数据模型使用的稳定值。
    failed: int
    # 变量说明：`oldest_queue_seconds` 保存本模块或数据模型使用的稳定值。
    oldest_queue_seconds: float | None
    # 变量说明：`last_finished_at` 保存本模块或数据模型使用的稳定值。
    last_finished_at: str | None


# 类说明：`RetrievalSearchRequest` 封装本模块内聚的数据和行为。
class RetrievalSearchRequest(StrictModel):
    # 变量说明：`query` 保存本模块或数据模型使用的稳定值。
    query: str = Field(min_length=1, max_length=500)
    # 变量说明：`top_k` 保存本模块或数据模型使用的稳定值。
    top_k: int | None = Field(default=None, ge=1, le=10)
    # 变量说明：`mode` 保存本模块或数据模型使用的稳定值。
    mode: Literal["frozen", "bm25", "dense", "hybrid"] = "frozen"
    # 变量说明：`component` 保存本模块或数据模型使用的稳定值。
    component: str | None = Field(default=None, min_length=1, max_length=64)
    # 变量说明：`product_version` 保存本模块或数据模型使用的稳定值。
    product_version: str | None = Field(default=None, min_length=1, max_length=32)


# 类说明：`RetrievalItem` 封装本模块内聚的数据和行为。
class RetrievalItem(StrictModel):
    # 变量说明：`rank` 保存本模块或数据模型使用的稳定值。
    rank: int
    # 变量说明：`chunk_id` 保存本模块或数据模型使用的稳定值。
    chunk_id: str
    # 变量说明：`doc_id` 保存本模块或数据模型使用的稳定值。
    doc_id: str
    # 变量说明：`title` 保存本模块或数据模型使用的稳定值。
    title: str
    # 变量说明：`section_path` 保存本模块或数据模型使用的稳定值。
    section_path: str
    # 变量说明：`excerpt` 保存本模块或数据模型使用的稳定值。
    excerpt: str
    # 变量说明：`component` 保存本模块或数据模型使用的稳定值。
    component: list[str]
    # 变量说明：`product` 保存本模块或数据模型使用的稳定值。
    product: str
    # 变量说明：`version_scope` 保存本模块或数据模型使用的稳定值。
    version_scope: list[str]
    # 变量说明：`risk_level` 保存本模块或数据模型使用的稳定值。
    risk_level: str
    # 变量说明：`source_id` 保存本模块或数据模型使用的稳定值。
    source_id: str
    # 变量说明：`source_url` 保存本模块或数据模型使用的稳定值。
    source_url: str | None
    # 变量说明：`source_version` 保存本模块或数据模型使用的稳定值。
    source_version: str
    # 变量说明：`maintained_at` 保存本模块或数据模型使用的稳定值。
    maintained_at: str
    # 变量说明：`evidence_url` 保存本模块或数据模型使用的稳定值。
    evidence_url: str
    # 变量说明：`bm25_score` 保存本模块或数据模型使用的稳定值。
    bm25_score: float
    # 变量说明：`dense_score` 保存本模块或数据模型使用的稳定值。
    dense_score: float | None
    # 变量说明：`rrf_score` 保存本模块或数据模型使用的稳定值。
    rrf_score: float


# 类说明：`RetrievalSearchResponse` 封装本模块内聚的数据和行为。
class RetrievalSearchResponse(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int = 1
    # 变量说明：`kb_release_id` 保存本模块或数据模型使用的稳定值。
    kb_release_id: str
    # 变量说明：`mode` 保存本模块或数据模型使用的稳定值。
    mode: str
    # 变量说明：`status` 保存本模块或数据模型使用的稳定值。
    status: Literal["evidence_found", "insufficient_evidence"]
    # 变量说明：`elapsed_ms` 保存本模块或数据模型使用的稳定值。
    elapsed_ms: float
    # 变量说明：`items` 保存本模块或数据模型使用的稳定值。
    items: list[RetrievalItem]


# 类说明：`KnowledgeChunkResponse` 封装本模块内聚的数据和行为。
class KnowledgeChunkResponse(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int = 1
    # 变量说明：`kb_release_id` 保存本模块或数据模型使用的稳定值。
    kb_release_id: str
    # 变量说明：`chunk_id` 保存本模块或数据模型使用的稳定值。
    chunk_id: str
    # 变量说明：`doc_id` 保存本模块或数据模型使用的稳定值。
    doc_id: str
    # 变量说明：`title` 保存本模块或数据模型使用的稳定值。
    title: str
    # 变量说明：`section_path` 保存本模块或数据模型使用的稳定值。
    section_path: str
    # 变量说明：`text` 保存本模块或数据模型使用的稳定值。
    text: str
    # 变量说明：`component` 保存本模块或数据模型使用的稳定值。
    component: list[str]
    # 变量说明：`product` 保存本模块或数据模型使用的稳定值。
    product: str
    # 变量说明：`version_scope` 保存本模块或数据模型使用的稳定值。
    version_scope: list[str]
    # 变量说明：`risk_level` 保存本模块或数据模型使用的稳定值。
    risk_level: str
    # 变量说明：`source_id` 保存本模块或数据模型使用的稳定值。
    source_id: str
    # 变量说明：`source_url` 保存本模块或数据模型使用的稳定值。
    source_url: str | None
    # 变量说明：`source_version` 保存本模块或数据模型使用的稳定值。
    source_version: str
    # 变量说明：`maintained_at` 保存本模块或数据模型使用的稳定值。
    maintained_at: str


# 类说明：`KnowledgeReleaseResponse` 封装本模块内聚的数据和行为。
class KnowledgeReleaseResponse(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int
    # 变量说明：`kb_release_id` 保存本模块或数据模型使用的稳定值。
    kb_release_id: str
    # 变量说明：`corpus_hash` 保存本模块或数据模型使用的稳定值。
    corpus_hash: str
    # 变量说明：`index_hash` 保存本模块或数据模型使用的稳定值。
    index_hash: str
    # 变量说明：`model_revision` 保存本模块或数据模型使用的稳定值。
    model_revision: str
    # 变量说明：`model_hash` 保存本模块或数据模型使用的稳定值。
    model_hash: str
    # 变量说明：`default_mode` 保存本模块或数据模型使用的稳定值。
    default_mode: str
    # 变量说明：`default_k` 保存本模块或数据模型使用的稳定值。
    default_k: int
    # 变量说明：`gate_threshold` 保存本模块或数据模型使用的稳定值。
    gate_threshold: float
    # 变量说明：`chunk_variant` 保存本模块或数据模型使用的稳定值。
    chunk_variant: str
    # 变量说明：`chunk_count` 保存本模块或数据模型使用的稳定值。
    chunk_count: int


# 类说明：`RagReportRequest` 封装本模块内聚的数据和行为。
class RagReportRequest(StrictModel):
    # 变量说明：`query` 保存本模块或数据模型使用的稳定值。
    query: str = Field(min_length=1, max_length=500)
    # 变量说明：`component` 保存本模块或数据模型使用的稳定值。
    component: str | None = Field(default=None, min_length=1, max_length=64)
    # 变量说明：`product_version` 保存本模块或数据模型使用的稳定值。
    product_version: str | None = Field(default=None, min_length=1, max_length=32)
    # 变量说明：`mode` 保存本模块或数据模型使用的稳定值。
    mode: Literal["auto", "template"] = "auto"


# 类说明：`RagReleaseResponse` 封装本模块内聚的数据和行为。
class RagReleaseResponse(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int
    # 变量说明：`rag_version` 保存本模块或数据模型使用的稳定值。
    rag_version: str
    # 变量说明：`kb_release_id` 保存本模块或数据模型使用的稳定值。
    kb_release_id: str
    # 变量说明：`provider` 保存本模块或数据模型使用的稳定值。
    provider: str
    # 变量说明：`model` 保存本模块或数据模型使用的稳定值。
    model: str
    # 变量说明：`prompt_version` 保存本模块或数据模型使用的稳定值。
    prompt_version: str
    # 变量说明：`prompt_hash` 保存本模块或数据模型使用的稳定值。
    prompt_hash: str
    # 变量说明：`config_hash` 保存本模块或数据模型使用的稳定值。
    config_hash: str
    # 变量说明：`online_configured` 保存本模块或数据模型使用的稳定值。
    online_configured: bool
    # 变量说明：`reranker_enabled` 保存本模块或数据模型使用的稳定值。
    reranker_enabled: bool


# 类说明：`DiagnosisRequest` 封装本模块内聚的数据和行为。
class DiagnosisRequest(StrictModel):
    # 变量说明：`event_id` 保存本模块或数据模型使用的稳定值。
    event_id: str = Field(min_length=1, max_length=64, pattern=r"^evt_[A-Za-z0-9_-]+$")
    # 变量说明：`mode` 保存本模块或数据模型使用的稳定值。
    mode: Literal["auto", "template"] = "auto"


# 类说明：`DiagnosisResponse` 封装本模块内聚的数据和行为。
class DiagnosisResponse(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int = 1
    # 变量说明：`diagnosis_id` 保存本模块或数据模型使用的稳定值。
    diagnosis_id: str
    # 变量说明：`event_id` 保存本模块或数据模型使用的稳定值。
    event_id: str
    # 变量说明：`revision` 保存本模块或数据模型使用的稳定值。
    revision: int
    # 变量说明：`status` 保存本模块或数据模型使用的稳定值。
    status: str
    # 变量说明：`current_node` 保存本模块或数据模型使用的稳定值。
    current_node: str
    # 变量说明：`mode` 保存本模块或数据模型使用的稳定值。
    mode: str
    # 变量说明：`state` 保存本模块或数据模型使用的稳定值。
    state: dict[str, Any]
    # 变量说明：`budget` 保存本模块或数据模型使用的稳定值。
    budget: dict[str, Any]
    # 变量说明：`report_id` 保存本模块或数据模型使用的稳定值。
    report_id: str | None = None
    # 变量说明：`approval_id` 保存本模块或数据模型使用的稳定值。
    approval_id: str | None = None
    # 变量说明：`error` 保存本模块或数据模型使用的稳定值。
    error: dict[str, Any] | None = None
    # 变量说明：`created_at` 保存本模块或数据模型使用的稳定值。
    created_at: str
    # 变量说明：`started_at` 保存本模块或数据模型使用的稳定值。
    started_at: str | None = None
    # 变量说明：`finished_at` 保存本模块或数据模型使用的稳定值。
    finished_at: str | None = None
    # 变量说明：`updated_at` 保存本模块或数据模型使用的稳定值。
    updated_at: str
    # 变量说明：`deduplicated` 保存本模块或数据模型使用的稳定值。
    deduplicated: bool = False
    # 变量说明：`links` 保存本模块或数据模型使用的稳定值。
    links: dict[str, str]


# 类说明：`ToolCallItem` 封装本模块内聚的数据和行为。
class ToolCallItem(StrictModel):
    # 变量说明：`tool_call_id` 保存本模块或数据模型使用的稳定值。
    tool_call_id: str
    # 变量说明：`ordinal` 保存本模块或数据模型使用的稳定值。
    ordinal: int
    # 变量说明：`tool_name` 保存本模块或数据模型使用的稳定值。
    tool_name: str
    # 变量说明：`status` 保存本模块或数据模型使用的稳定值。
    status: str
    # 变量说明：`args_hash` 保存本模块或数据模型使用的稳定值。
    args_hash: str
    # 变量说明：`started_at` 保存本模块或数据模型使用的稳定值。
    started_at: str
    # 变量说明：`finished_at` 保存本模块或数据模型使用的稳定值。
    finished_at: str | None = None
    # 变量说明：`result` 保存本模块或数据模型使用的稳定值。
    result: dict[str, Any] | None = None


# 类说明：`ToolCallList` 封装本模块内聚的数据和行为。
class ToolCallList(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int = 1
    # 变量说明：`items` 保存本模块或数据模型使用的稳定值。
    items: list[ToolCallItem]


# 类说明：`ApprovalDecisionRequest` 封装本模块内聚的数据和行为。
class ApprovalDecisionRequest(StrictModel):
    # 变量说明：`decision` 保存本模块或数据模型使用的稳定值。
    decision: Literal["approve", "reject", "request_more_evidence"]
    # 变量说明：`report_hash` 保存本模块或数据模型使用的稳定值。
    report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    # 变量说明：`revision` 保存本模块或数据模型使用的稳定值。
    revision: int = Field(ge=1, le=2)
    # 变量说明：`reason` 保存本模块或数据模型使用的稳定值。
    reason: str = Field(min_length=1, max_length=1000)


# 类说明：`ApprovalResponse` 封装本模块内聚的数据和行为。
class ApprovalResponse(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int = 1
    # 变量说明：`approval_id` 保存本模块或数据模型使用的稳定值。
    approval_id: str
    # 变量说明：`diagnosis_id` 保存本模块或数据模型使用的稳定值。
    diagnosis_id: str
    # 变量说明：`report_id` 保存本模块或数据模型使用的稳定值。
    report_id: str
    # 变量说明：`report_hash` 保存本模块或数据模型使用的稳定值。
    report_hash: str
    # 变量说明：`revision` 保存本模块或数据模型使用的稳定值。
    revision: int
    # 变量说明：`action_ids` 保存本模块或数据模型使用的稳定值。
    action_ids: list[str]
    # 变量说明：`status` 保存本模块或数据模型使用的稳定值。
    status: str
    # 变量说明：`reviewer_id` 保存本模块或数据模型使用的稳定值。
    reviewer_id: str | None = None
    # 变量说明：`reason` 保存本模块或数据模型使用的稳定值。
    reason: str | None = None
    # 变量说明：`created_at` 保存本模块或数据模型使用的稳定值。
    created_at: str
    # 变量说明：`expires_at` 保存本模块或数据模型使用的稳定值。
    expires_at: str
    # 变量说明：`decided_at` 保存本模块或数据模型使用的稳定值。
    decided_at: str | None = None
    # 变量说明：`next_diagnosis_id` 保存本模块或数据模型使用的稳定值。
    next_diagnosis_id: str | None = None


# 类说明：`ApprovalList` 封装本模块内聚的数据和行为。
class ApprovalList(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int = 1
    # 变量说明：`items` 保存本模块或数据模型使用的稳定值。
    items: list[ApprovalResponse]


# 类说明：`AgentReleaseResponse` 封装本模块内聚的数据和行为。
class AgentReleaseResponse(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int
    # 变量说明：`product_version` 保存本模块或数据模型使用的稳定值。
    product_version: str
    # 变量说明：`agent_version` 保存本模块或数据模型使用的稳定值。
    agent_version: str
    # 变量说明：`candidate_hash` 保存本模块或数据模型使用的稳定值。
    candidate_hash: str
    # 变量说明：`release_id` 保存本模块或数据模型使用的稳定值。
    release_id: str
    # 变量说明：`rag_version` 保存本模块或数据模型使用的稳定值。
    rag_version: str
    # 变量说明：`kb_release_id` 保存本模块或数据模型使用的稳定值。
    kb_release_id: str
    # 变量说明：`tool_manifest_hash` 保存本模块或数据模型使用的稳定值。
    tool_manifest_hash: str
    # 变量说明：`risk_policy_hash` 保存本模块或数据模型使用的稳定值。
    risk_policy_hash: str
    # 变量说明：`prompt_version` 保存本模块或数据模型使用的稳定值。
    prompt_version: str
