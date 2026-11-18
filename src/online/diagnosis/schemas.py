"""定义诊断输入输出：工具结果、证据、假设与报告。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolResult(StrictModel):
    ok: bool
    data: dict
    error: dict | None = None
    provenance: dict = Field(default_factory=dict)
    elapsed_ms: float = 0.0
    truncated: bool = False


class Evidence(StrictModel):
    evidence_id: str
    kind: Literal["log", "metric", "doc", "incident", "model", "trace"]
    source_ref: str
    version: str
    observed_at: str | None = None
    observed_until: str | None = None
    excerpt_redacted: str
    evidence_hash: str
    # root_cause_code 是知识卡携带的根因码，可为空。
    root_cause_code: str | None = None


class Hypothesis(StrictModel):
    hypothesis_id: str
    description: str = Field(min_length=1, max_length=800)
    component: str | None = None
    # root_cause_code 是候选原因对应的受控根因码。
    root_cause_code: str | None = None
    support_ids: list[str] = Field(max_length=12)
    counter_ids: list[str] = Field(max_length=12)
    missing_checks: list[str] = Field(max_length=8)
    support_score: float = Field(ge=0, le=1)
    confidence_level: Literal["high", "medium", "low", "unknown"]


# ROOT_CAUSE_CODES 是受控根因码枚举，与 real_incident_protocol 保持一致。
ROOT_CAUSE_CODES = ("NN_AVAILABILITY", "NN_SAFE_MODE", "DN_HEARTBEAT", "DN_VOLUME",
                    "BLOCK_REPLICATION", "BLOCK_REPORT", "JOURNAL_QUORUM",
                    "HA_STANDBY_LAG", "CLIENT_WRITE_PIPELINE", "NETWORK_CONNECTIVITY",
                    "UNKNOWN")


ActionType = Literal[
    "read_only_check", "observe", "collect_evidence", "restart_service",
    "delete_data", "traffic_shift", "block_access", "database_write", "unknown",
]


class ActionAdvice(StrictModel):
    action_id: str
    action_type: ActionType
    description: str = Field(min_length=1, max_length=800)
    preconditions: list[str] = Field(max_length=8)
    risk: Literal["low", "medium", "high", "unknown"]
    citation_ids: list[str] = Field(max_length=12)
    execution_allowed: Literal[False] = False
    approval_required: bool


class GeneratedReportBody(StrictModel):
    summary: str = Field(min_length=1, max_length=1200)
    observed_facts: list[str] = Field(max_length=12)
    hypotheses: list[Hypothesis] = Field(max_length=5)
    checks: list[ActionAdvice] = Field(max_length=12)
    missing_information: list[str] = Field(max_length=12)
    limitations: list[str] = Field(min_length=1, max_length=12)


class IncidentReport(StrictModel):
    schema_version: int = 1
    report_id: str
    diagnosis_id: str
    incident_id: str
    revision: int = Field(ge=1, le=2)
    diagnosis_status: Literal[
        "EVIDENCE_SUPPORTED", "INSUFFICIENT_EVIDENCE", "DEGRADED_TEMPLATE"
    ]
    summary: str
    observation_window: dict
    anomaly: dict
    observed_facts: list[str]
    hypotheses: list[Hypothesis]
    retrieved_knowledge: list[dict]
    checks: list[ActionAdvice]
    risk_level: Literal["low", "medium", "high", "unknown"]
    confidence_level: Literal["high", "medium", "low", "unknown"]
    requires_review: bool
    review_reasons: list[str]
    missing_information: list[str]
    limitations: list[str]
    evidence: list[Evidence]
    provenance: dict
    report_hash: str


class RouterDecision(StrictModel):
    next_tools: list[Literal["query_metrics", "search_similar_incidents"]] = Field(
        max_length=2)
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_tools(self):
        if len(set(self.next_tools)) != len(self.next_tools):
            raise ValueError("Router tools must be unique")
        return self
