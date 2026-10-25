"""
Strict contracts shared by the v1.2 public and real-incident data paths.

所有对外接口的输入输出格式都在这里以 Pydantic 模型的方式严格定义。
incident_v12.py、v12_import.py 都依赖这里的模型做校验。
没有它，任何外部数据（无论是公共数据集的 JSONL 还是人工标注的 Incident JSON）都是不可信的

"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# 类说明：`StrictModel` 封装本模块内聚的数据和行为。
class StrictModel(BaseModel):
    # 变量说明：`model_config` 保存本模块或数据模型使用的稳定值。
    model_config = ConfigDict(extra="forbid")


# 类说明：`EvidenceRefV12` 封装本模块内聚的数据和行为。
class EvidenceRefV12(StrictModel):
    # 变量说明：`ref_id` 保存本模块或数据模型使用的稳定值。
    ref_id: str = Field(min_length=1, max_length=160)
    # 变量说明：`content_sha256` 保存本模块或数据模型使用的稳定值。
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    # 变量说明：`relative_path` 保存本模块或数据模型使用的稳定值。
    relative_path: str | None = Field(default=None, max_length=500)
    # 变量说明：`bytes` 保存本模块或数据模型使用的稳定值。
    bytes: int | None = Field(default=None, ge=0)
    # 变量说明：`redaction_status` 保存本模块或数据模型使用的稳定值。
    redaction_status: Literal["not_exported", "approved_redacted"] = "not_exported"
    # 变量说明：`observed_at` 保存本模块或数据模型使用的稳定值。
    observed_at: str | None = None


# 类说明：`MetricEligibilityV12` 封装本模块内聚的数据和行为。
class MetricEligibilityV12(StrictModel):
    # 变量说明：`public_injection_benchmark` 保存本模块或数据模型使用的稳定值。
    public_injection_benchmark: bool
    # 变量说明：`production_root_cause_ranking` 保存本模块或数据模型使用的稳定值。
    production_root_cause_ranking: bool = False
    # 变量说明：`mttd` 保存本模块或数据模型使用的稳定值。
    mttd: bool = False
    # 变量说明：`reasons` 保存本模块或数据模型使用的稳定值。
    reasons: list[str] = Field(default_factory=list, max_length=20)

    # 方法说明：`production_metrics_require_no_exclusion_reasons` 完成当前步骤的业务处理；参数为 无显式业务参数。
    @model_validator(mode="after")
    def production_metrics_require_no_exclusion_reasons(self):
        if (self.production_root_cause_ranking or self.mttd) and self.reasons:
            raise ValueError("Eligible production metrics cannot have exclusion reasons")
        return self


# 类说明：`ExternalEventV12` 封装本模块内聚的数据和行为。
class ExternalEventV12(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: Literal[1]
    # 变量说明：`adapter_version` 保存本模块或数据模型使用的稳定值。
    adapter_version: str
    # 变量说明：`dataset` 保存本模块或数据模型使用的稳定值。
    dataset: Literal["loghub_hadoop", "hdfs_v3_tracebench"]
    # 变量说明：`event_id` 保存本模块或数据模型使用的稳定值。
    event_id: str = Field(pattern=r"^evt_[A-Za-z0-9_-]+$")
    # 变量说明：`source_unit_id` 保存本模块或数据模型使用的稳定值。
    source_unit_id: str
    # 变量说明：`group_id` 保存本模块或数据模型使用的稳定值。
    group_id: str
    # 变量说明：`cluster_alias` 保存本模块或数据模型使用的稳定值。
    cluster_alias: str = Field(pattern=r"^cluster_[A-Za-z0-9_-]+$")
    # 变量说明：`product_version` 保存本模块或数据模型使用的稳定值。
    product_version: str | None = None
    # 变量说明：`workload` 保存本模块或数据模型使用的稳定值。
    workload: str
    # 变量说明：`scenario_kind` 保存本模块或数据模型使用的稳定值。
    scenario_kind: Literal["normal", "injected_fault", "compound"]
    # 变量说明：`anomaly_label` 保存本模块或数据模型使用的稳定值。
    anomaly_label: Literal["normal", "anomaly", "mixed"]
    # 变量说明：`injection_label` 保存本模块或数据模型使用的稳定值。
    injection_label: str | None
    # 变量说明：`root_cause_label` 保存本模块或数据模型使用的稳定值。
    root_cause_label: None = None
    # 变量说明：`label_provenance` 保存本模块或数据模型使用的稳定值。
    label_provenance: dict[str, Any]
    # 变量说明：`timestamps` 保存本模块或数据模型使用的稳定值。
    timestamps: dict[str, Any]
    # 变量说明：`components` 保存本模块或数据模型使用的稳定值。
    components: list[str]
    # 变量说明：`signals` 保存本模块或数据模型使用的稳定值。
    signals: list[str]
    # 变量说明：`observations` 保存本模块或数据模型使用的稳定值。
    observations: dict[str, Any]
    # 变量说明：`evidence_refs` 保存本模块或数据模型使用的稳定值。
    evidence_refs: list[EvidenceRefV12]
    # 变量说明：`benchmark_target` 保存本模块或数据模型使用的稳定值。
    benchmark_target: Literal["injection_label"]
    # 变量说明：`metric_eligibility` 保存本模块或数据模型使用的稳定值。
    metric_eligibility: MetricEligibilityV12


# 类说明：`SafeLogTemplateV12` 封装本模块内聚的数据和行为。
class SafeLogTemplateV12(StrictModel):
    # 变量说明：`log_id` 保存本模块或数据模型使用的稳定值。
    log_id: str
    # 变量说明：`timestamp` 保存本模块或数据模型使用的稳定值。
    timestamp: str | None = None
    # 变量说明：`level` 保存本模块或数据模型使用的稳定值。
    level: str | None = None
    # 变量说明：`component` 保存本模块或数据模型使用的稳定值。
    component: str
    # 变量说明：`redacted_message` 保存本模块或数据模型使用的稳定值。
    redacted_message: str = Field(max_length=500)
    # 变量说明：`template_id` 保存本模块或数据模型使用的稳定值。
    template_id: str
    # 变量说明：`count` 保存本模块或数据模型使用的稳定值。
    count: int = Field(ge=1)


# 类说明：`TraceSummaryV12` 封装本模块内聚的数据和行为。
class TraceSummaryV12(StrictModel):
    # 变量说明：`task_count` 保存本模块或数据模型使用的稳定值。
    task_count: int = Field(ge=0)
    # 变量说明：`report_count` 保存本模块或数据模型使用的稳定值。
    report_count: int = Field(ge=0)
    # 变量说明：`edge_count` 保存本模块或数据模型使用的稳定值。
    edge_count: int = Field(ge=0)
    # 变量说明：`operation_count` 保存本模块或数据模型使用的稳定值。
    operation_count: int = Field(ge=0)
    # 变量说明：`operation_type_count` 保存本模块或数据模型使用的稳定值。
    operation_type_count: int = Field(ge=0)
    # 变量说明：`failed_event_count` 保存本模块或数据模型使用的稳定值。
    failed_event_count: int = Field(ge=0)
    # 变量说明：`component_counts` 保存本模块或数据模型使用的稳定值。
    component_counts: dict[str, int]
    # 变量说明：`top_operations` 保存本模块或数据模型使用的稳定值。
    top_operations: dict[str, int]


# 类说明：`DiagnosticSnapshotV12` 封装本模块内聚的数据和行为。
class DiagnosticSnapshotV12(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: Literal[1] = 1
    # 变量说明：`adapter_version` 保存本模块或数据模型使用的稳定值。
    adapter_version: str
    # 变量说明：`event_id` 保存本模块或数据模型使用的稳定值。
    event_id: str = Field(pattern=r"^evt_[A-Za-z0-9_-]+$")
    # 变量说明：`dataset` 保存本模块或数据模型使用的稳定值。
    dataset: Literal["loghub_hadoop", "hdfs_v3_tracebench"]
    # 变量说明：`source_type` 保存本模块或数据模型使用的稳定值。
    source_type: Literal["public_dataset", "authorized_incident"] = "public_dataset"
    # 变量说明：`cluster_alias` 保存本模块或数据模型使用的稳定值。
    cluster_alias: str
    # 变量说明：`product_version` 保存本模块或数据模型使用的稳定值。
    product_version: str | None = None
    # 变量说明：`components` 保存本模块或数据模型使用的稳定值。
    components: list[str]
    # 变量说明：`observation_window` 保存本模块或数据模型使用的稳定值。
    observation_window: dict[str, str | None]
    # 变量说明：`log_templates` 保存本模块或数据模型使用的稳定值。
    log_templates: list[SafeLogTemplateV12] = Field(default_factory=list, max_length=100)
    # 变量说明：`trace_summary` 保存本模块或数据模型使用的稳定值。
    trace_summary: TraceSummaryV12 | None = None
    # 变量说明：`signals` 保存本模块或数据模型使用的稳定值。
    signals: list[str] = Field(default_factory=list, max_length=30)
    # 变量说明：`evidence_refs` 保存本模块或数据模型使用的稳定值。
    evidence_refs: list[EvidenceRefV12]
    # 变量说明：`snapshot_hash` 保存本模块或数据模型使用的稳定值。
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    # 方法说明：`require_observational_evidence` 完成当前步骤的业务处理；参数为 无显式业务参数。
    @model_validator(mode="after")
    def require_observational_evidence(self):
        if not self.log_templates and self.trace_summary is None:
            raise ValueError("A diagnostic snapshot requires log or trace observations")
        return self


# 类说明：`EvaluationLabelV12` 封装本模块内聚的数据和行为。
class EvaluationLabelV12(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: Literal[1] = 1
    # 变量说明：`event_id` 保存本模块或数据模型使用的稳定值。
    event_id: str = Field(pattern=r"^evt_[A-Za-z0-9_-]+$")
    # 变量说明：`dataset` 保存本模块或数据模型使用的稳定值。
    dataset: Literal["loghub_hadoop", "hdfs_v3_tracebench"]
    # 变量说明：`group_id` 保存本模块或数据模型使用的稳定值。
    group_id: str
    # 变量说明：`split` 保存本模块或数据模型使用的稳定值。
    split: Literal["development", "calibration", "independent_test"]
    # 变量说明：`anomaly_label` 保存本模块或数据模型使用的稳定值。
    anomaly_label: Literal["normal", "anomaly", "mixed"]
    # 变量说明：`injection_label` 保存本模块或数据模型使用的稳定值。
    injection_label: str | None
    # 变量说明：`root_cause_label` 保存本模块或数据模型使用的稳定值。
    root_cause_label: None = None
    # 变量说明：`metric_eligibility` 保存本模块或数据模型使用的稳定值。
    metric_eligibility: MetricEligibilityV12


# 类说明：`AuthorizationV1` 封装本模块内聚的数据和行为。
class AuthorizationV1(StrictModel):
    # 变量说明：`authorization_id` 保存本模块或数据模型使用的稳定值。
    authorization_id: str = Field(min_length=1, max_length=128)
    # 变量说明：`approved_at` 保存本模块或数据模型使用的稳定值。
    approved_at: datetime
    # 变量说明：`retention_until` 保存本模块或数据模型使用的稳定值。
    retention_until: datetime
    # 变量说明：`deletion_contact` 保存本模块或数据模型使用的稳定值。
    deletion_contact: str = Field(min_length=1, max_length=256)

    # 方法说明：`retention_after_approval` 完成当前步骤的业务处理；参数为 无显式业务参数。
    @model_validator(mode="after")
    def retention_after_approval(self):
        if self.retention_until <= self.approved_at:
            raise ValueError("retention_until must be after approved_at")
        return self


# 类说明：`IncidentTimestampsV1` 封装本模块内聚的数据和行为。
class IncidentTimestampsV1(StrictModel):
    # 变量说明：`fault_start` 保存本模块或数据模型使用的稳定值。
    fault_start: datetime | None
    # 变量说明：`first_observable_signal` 保存本模块或数据模型使用的稳定值。
    first_observable_signal: datetime | None
    # 变量说明：`agent_detected` 保存本模块或数据模型使用的稳定值。
    agent_detected: datetime | None
    # 变量说明：`human_confirmed` 保存本模块或数据模型使用的稳定值。
    human_confirmed: datetime | None
    # 变量说明：`recovered` 保存本模块或数据模型使用的稳定值。
    recovered: datetime | None
    # 变量说明：`timezone_source` 保存本模块或数据模型使用的稳定值。
    timezone_source: str | None = None

    # 方法说明：`timezone_required` 完成当前步骤的业务处理；参数为 `value`。
    @field_validator("fault_start", "first_observable_signal", "agent_detected",
                     "human_confirmed", "recovered")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Incident timestamps must include a timezone")
        return value


# 类说明：`IncidentEvidenceRefV1` 封装本模块内聚的数据和行为。
class IncidentEvidenceRefV1(StrictModel):
    # 变量说明：`ref_id` 保存本模块或数据模型使用的稳定值。
    ref_id: str
    # 变量说明：`content_sha256` 保存本模块或数据模型使用的稳定值。
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    # 变量说明：`redaction_status` 保存本模块或数据模型使用的稳定值。
    redaction_status: Literal["approved_redacted"]
    # 变量说明：`observed_at` 保存本模块或数据模型使用的稳定值。
    observed_at: datetime | None


# 类说明：`DiagnosisSnapshotRefV1` 封装本模块内聚的数据和行为。
class DiagnosisSnapshotRefV1(StrictModel):
    # 变量说明：`cutoff_time` 保存本模块或数据模型使用的稳定值。
    cutoff_time: datetime
    # 变量说明：`log_refs` 保存本模块或数据模型使用的稳定值。
    log_refs: list[IncidentEvidenceRefV1]
    # 变量说明：`metric_refs` 保存本模块或数据模型使用的稳定值。
    metric_refs: list[IncidentEvidenceRefV1]
    # 变量说明：`ticket_refs` 保存本模块或数据模型使用的稳定值。
    ticket_refs: list[IncidentEvidenceRefV1]

    # 方法说明：`cutoff_has_timezone` 完成当前步骤的业务处理；参数为 `value`。
    @field_validator("cutoff_time")
    @classmethod
    def cutoff_has_timezone(cls, value):
        if value.tzinfo is None:
            raise ValueError("cutoff_time must include a timezone")
        return value


# 类说明：`IncidentLabelsV1` 封装本模块内聚的数据和行为。
class IncidentLabelsV1(StrictModel):
    # 变量说明：`root_cause_code` 保存本模块或数据模型使用的稳定值。
    root_cause_code: str | None
    # 变量说明：`confidence` 保存本模块或数据模型使用的稳定值。
    confidence: Literal["confirmed", "high", "medium", "low", "unknown"]
    # 变量说明：`review_status` 保存本模块或数据模型使用的稳定值。
    review_status: Literal["draft", "reviewed", "adjudicated", "unresolved"]
    # 变量说明：`evidence_refs` 保存本模块或数据模型使用的稳定值。
    evidence_refs: list[str]
    # 变量说明：`creator_id` 保存本模块或数据模型使用的稳定值。
    creator_id: str | None = None
    # 变量说明：`reviewer_id` 保存本模块或数据模型使用的稳定值。
    reviewer_id: str | None = None
    # 变量说明：`adjudicator_id` 保存本模块或数据模型使用的稳定值。
    adjudicator_id: str | None = None


# 类说明：`IncidentRecordV1` 封装本模块内聚的数据和行为。
class IncidentRecordV1(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: Literal[1]
    # 变量说明：`incident_id` 保存本模块或数据模型使用的稳定值。
    incident_id: str = Field(pattern=r"^inc_[A-Za-z0-9_-]{8,64}$")
    # 变量说明：`cluster_alias` 保存本模块或数据模型使用的稳定值。
    cluster_alias: str = Field(pattern=r"^cluster_[A-Za-z0-9_-]+$")
    # 变量说明：`product_version` 保存本模块或数据模型使用的稳定值。
    product_version: str | None = Field(default=None, pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    # 变量说明：`fault_family` 保存本模块或数据模型使用的稳定值。
    fault_family: str | None = None
    # 变量说明：`authorization` 保存本模块或数据模型使用的稳定值。
    authorization: AuthorizationV1
    # 变量说明：`timestamps` 保存本模块或数据模型使用的稳定值。
    timestamps: IncidentTimestampsV1
    # 变量说明：`diagnosis_snapshot` 保存本模块或数据模型使用的稳定值。
    diagnosis_snapshot: DiagnosisSnapshotRefV1
    # 变量说明：`labels` 保存本模块或数据模型使用的稳定值。
    labels: IncidentLabelsV1
