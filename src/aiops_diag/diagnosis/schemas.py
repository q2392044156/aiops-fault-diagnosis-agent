"""模块说明：定义当前模块输入输出的 Pydantic 数据结构。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# 类说明：`StrictModel` 封装本模块内聚的数据和行为。
class StrictModel(BaseModel):
    # 变量说明：`model_config` 保存本模块或数据模型使用的稳定值。
    model_config = ConfigDict(extra="forbid")


# 类说明：`ToolResult` 封装本模块内聚的数据和行为。
class ToolResult(StrictModel):
    # 变量说明：`ok` 保存本模块或数据模型使用的稳定值。
    ok: bool
    # 变量说明：`data` 保存本模块或数据模型使用的稳定值。
    data: dict
    # 变量说明：`error` 保存本模块或数据模型使用的稳定值。
    error: dict | None = None
    # 变量说明：`provenance` 保存本模块或数据模型使用的稳定值。
    provenance: dict = Field(default_factory=dict)
    # 变量说明：`elapsed_ms` 保存本模块或数据模型使用的稳定值。
    elapsed_ms: float = 0.0
    # 变量说明：`truncated` 保存本模块或数据模型使用的稳定值。
    truncated: bool = False


# 类说明：`Evidence` 封装本模块内聚的数据和行为。
class Evidence(StrictModel):
    # 变量说明：`evidence_id` 保存本模块或数据模型使用的稳定值。
    evidence_id: str
    # 变量说明：`kind` 保存本模块或数据模型使用的稳定值。
    kind: Literal["log", "metric", "doc", "incident", "model", "trace"]
    # 变量说明：`source_ref` 保存本模块或数据模型使用的稳定值。
    source_ref: str
    # 变量说明：`version` 保存本模块或数据模型使用的稳定值。
    version: str
    # 变量说明：`observed_at` 保存本模块或数据模型使用的稳定值。
    observed_at: str | None = None
    # 变量说明：`observed_until` 保存本模块或数据模型使用的稳定值。
    observed_until: str | None = None
    # 变量说明：`excerpt_redacted` 保存本模块或数据模型使用的稳定值。
    excerpt_redacted: str
    # 变量说明：`evidence_hash` 保存本模块或数据模型使用的稳定值。
    evidence_hash: str
    # 变量说明：root_cause_code 是知识卡携带的根因码，可为空。
    root_cause_code: str | None = None


# 类说明：`Hypothesis` 封装本模块内聚的数据和行为。
class Hypothesis(StrictModel):
    # 变量说明：`hypothesis_id` 保存本模块或数据模型使用的稳定值。
    hypothesis_id: str
    # 变量说明：`description` 保存本模块或数据模型使用的稳定值。
    description: str = Field(min_length=1, max_length=800)
    # 变量说明：`component` 保存本模块或数据模型使用的稳定值。
    component: str | None = None
    # 变量说明：root_cause_code 是候选原因对应的受控根因码。
    root_cause_code: str | None = None
    # 变量说明：`support_ids` 保存本模块或数据模型使用的稳定值。
    support_ids: list[str] = Field(max_length=12)
    # 变量说明：`counter_ids` 保存本模块或数据模型使用的稳定值。
    counter_ids: list[str] = Field(max_length=12)
    # 变量说明：`missing_checks` 保存本模块或数据模型使用的稳定值。
    missing_checks: list[str] = Field(max_length=8)
    # 变量说明：`support_score` 保存本模块或数据模型使用的稳定值。
    support_score: float = Field(ge=0, le=1)
    # 变量说明：`confidence_level` 保存本模块或数据模型使用的稳定值。
    confidence_level: Literal["high", "medium", "low", "unknown"]


# 变量说明：ROOT_CAUSE_CODES 是受控根因码枚举，与 real_incident_protocol 保持一致。
ROOT_CAUSE_CODES = ("NN_AVAILABILITY", "NN_SAFE_MODE", "DN_HEARTBEAT", "DN_VOLUME",
                    "BLOCK_REPLICATION", "BLOCK_REPORT", "JOURNAL_QUORUM",
                    "HA_STANDBY_LAG", "CLIENT_WRITE_PIPELINE", "NETWORK_CONNECTIVITY",
                    "UNKNOWN")


# 变量说明：`ActionType` 保存本模块或数据模型使用的稳定值。
ActionType = Literal[
    "read_only_check", "observe", "collect_evidence", "restart_service",
    "delete_data", "traffic_shift", "block_access", "database_write", "unknown",
]


# 类说明：`ActionAdvice` 封装本模块内聚的数据和行为。
class ActionAdvice(StrictModel):
    # 变量说明：`action_id` 保存本模块或数据模型使用的稳定值。
    action_id: str
    # 变量说明：`action_type` 保存本模块或数据模型使用的稳定值。
    action_type: ActionType
    # 变量说明：`description` 保存本模块或数据模型使用的稳定值。
    description: str = Field(min_length=1, max_length=800)
    # 变量说明：`preconditions` 保存本模块或数据模型使用的稳定值。
    preconditions: list[str] = Field(max_length=8)
    # 变量说明：`risk` 保存本模块或数据模型使用的稳定值。
    risk: Literal["low", "medium", "high", "unknown"]
    # 变量说明：`citation_ids` 保存本模块或数据模型使用的稳定值。
    citation_ids: list[str] = Field(max_length=12)
    # 变量说明：`execution_allowed` 保存本模块或数据模型使用的稳定值。
    execution_allowed: Literal[False] = False
    # 变量说明：`approval_required` 保存本模块或数据模型使用的稳定值。
    approval_required: bool


# 类说明：`GeneratedReportBody` 封装本模块内聚的数据和行为。
class GeneratedReportBody(StrictModel):
    # 变量说明：`summary` 保存本模块或数据模型使用的稳定值。
    summary: str = Field(min_length=1, max_length=1200)
    # 变量说明：`observed_facts` 保存本模块或数据模型使用的稳定值。
    observed_facts: list[str] = Field(max_length=12)
    # 变量说明：`hypotheses` 保存本模块或数据模型使用的稳定值。
    hypotheses: list[Hypothesis] = Field(max_length=3)
    # 变量说明：`checks` 保存本模块或数据模型使用的稳定值。
    checks: list[ActionAdvice] = Field(max_length=12)
    # 变量说明：`missing_information` 保存本模块或数据模型使用的稳定值。
    missing_information: list[str] = Field(max_length=12)
    # 变量说明：`limitations` 保存本模块或数据模型使用的稳定值。
    limitations: list[str] = Field(min_length=1, max_length=12)


# 类说明：`IncidentReport` 封装本模块内聚的数据和行为。
class IncidentReport(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int = 1
    # 变量说明：`report_id` 保存本模块或数据模型使用的稳定值。
    report_id: str
    # 变量说明：`diagnosis_id` 保存本模块或数据模型使用的稳定值。
    diagnosis_id: str
    # 变量说明：`incident_id` 保存本模块或数据模型使用的稳定值。
    incident_id: str
    # 变量说明：`revision` 保存本模块或数据模型使用的稳定值。
    revision: int = Field(ge=1, le=2)
    # 变量说明：`diagnosis_status` 保存本模块或数据模型使用的稳定值。
    diagnosis_status: Literal[
        "EVIDENCE_SUPPORTED", "INSUFFICIENT_EVIDENCE", "DEGRADED_TEMPLATE"
    ]
    # 变量说明：`summary` 保存本模块或数据模型使用的稳定值。
    summary: str
    # 变量说明：`observation_window` 保存本模块或数据模型使用的稳定值。
    observation_window: dict
    # 变量说明：`anomaly` 保存本模块或数据模型使用的稳定值。
    anomaly: dict
    # 变量说明：`observed_facts` 保存本模块或数据模型使用的稳定值。
    observed_facts: list[str]
    # 变量说明：`hypotheses` 保存本模块或数据模型使用的稳定值。
    hypotheses: list[Hypothesis]
    # 变量说明：`retrieved_knowledge` 保存本模块或数据模型使用的稳定值。
    retrieved_knowledge: list[dict]
    # 变量说明：`checks` 保存本模块或数据模型使用的稳定值。
    checks: list[ActionAdvice]
    # 变量说明：`risk_level` 保存本模块或数据模型使用的稳定值。
    risk_level: Literal["low", "medium", "high", "unknown"]
    # 变量说明：`confidence_level` 保存本模块或数据模型使用的稳定值。
    confidence_level: Literal["high", "medium", "low", "unknown"]
    # 变量说明：`requires_review` 保存本模块或数据模型使用的稳定值。
    requires_review: bool
    # 变量说明：`review_reasons` 保存本模块或数据模型使用的稳定值。
    review_reasons: list[str]
    # 变量说明：`missing_information` 保存本模块或数据模型使用的稳定值。
    missing_information: list[str]
    # 变量说明：`limitations` 保存本模块或数据模型使用的稳定值。
    limitations: list[str]
    # 变量说明：`evidence` 保存本模块或数据模型使用的稳定值。
    evidence: list[Evidence]
    # 变量说明：`provenance` 保存本模块或数据模型使用的稳定值。
    provenance: dict
    # 变量说明：`report_hash` 保存本模块或数据模型使用的稳定值。
    report_hash: str


# 类说明：`RouterDecision` 封装本模块内聚的数据和行为。
class RouterDecision(StrictModel):
    # 变量说明：`next_tools` 保存本模块或数据模型使用的稳定值。
    next_tools: list[Literal["query_metrics", "search_similar_incidents"]] = Field(
        max_length=2)
    # 变量说明：`reason` 保存本模块或数据模型使用的稳定值。
    reason: str = Field(min_length=1, max_length=500)

    # 方法说明：`unique_tools` 完成当前步骤的业务处理；参数为 无显式业务参数。
    @model_validator(mode="after")
    def unique_tools(self):
        if len(set(self.next_tools)) != len(self.next_tools):
            raise ValueError("Router tools must be unique")
        return self
