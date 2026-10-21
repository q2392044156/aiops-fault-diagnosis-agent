"""Strict contracts shared by the v1.2 public and real-incident data paths."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceRefV12(StrictModel):
    ref_id: str = Field(min_length=1, max_length=160)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    relative_path: str | None = Field(default=None, max_length=500)
    bytes: int | None = Field(default=None, ge=0)
    redaction_status: Literal["not_exported", "approved_redacted"] = "not_exported"
    observed_at: str | None = None


class MetricEligibilityV12(StrictModel):
    public_injection_benchmark: bool
    production_root_cause_ranking: bool = False
    mttd: bool = False
    reasons: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def production_metrics_require_no_exclusion_reasons(self):
        if (self.production_root_cause_ranking or self.mttd) and self.reasons:
            raise ValueError("Eligible production metrics cannot have exclusion reasons")
        return self


class ExternalEventV12(StrictModel):
    schema_version: Literal[1]
    adapter_version: str
    dataset: Literal["loghub_hadoop", "hdfs_v3_tracebench"]
    event_id: str = Field(pattern=r"^evt_[A-Za-z0-9_-]+$")
    source_unit_id: str
    group_id: str
    cluster_alias: str = Field(pattern=r"^cluster_[A-Za-z0-9_-]+$")
    product_version: str | None = None
    workload: str
    scenario_kind: Literal["normal", "injected_fault", "compound"]
    anomaly_label: Literal["normal", "anomaly", "mixed"]
    injection_label: str | None
    root_cause_label: None = None
    label_provenance: dict[str, Any]
    timestamps: dict[str, Any]
    components: list[str]
    signals: list[str]
    observations: dict[str, Any]
    evidence_refs: list[EvidenceRefV12]
    benchmark_target: Literal["injection_label"]
    metric_eligibility: MetricEligibilityV12


class SafeLogTemplateV12(StrictModel):
    log_id: str
    timestamp: str | None = None
    level: str | None = None
    component: str
    redacted_message: str = Field(max_length=500)
    template_id: str
    count: int = Field(ge=1)


class TraceSummaryV12(StrictModel):
    task_count: int = Field(ge=0)
    report_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    operation_count: int = Field(ge=0)
    operation_type_count: int = Field(ge=0)
    failed_event_count: int = Field(ge=0)
    component_counts: dict[str, int]
    top_operations: dict[str, int]


class DiagnosticSnapshotV12(StrictModel):
    schema_version: Literal[1] = 1
    adapter_version: str
    event_id: str = Field(pattern=r"^evt_[A-Za-z0-9_-]+$")
    dataset: Literal["loghub_hadoop", "hdfs_v3_tracebench"]
    source_type: Literal["public_dataset", "authorized_incident"] = "public_dataset"
    cluster_alias: str
    product_version: str | None = None
    components: list[str]
    observation_window: dict[str, str | None]
    log_templates: list[SafeLogTemplateV12] = Field(default_factory=list, max_length=100)
    trace_summary: TraceSummaryV12 | None = None
    signals: list[str] = Field(default_factory=list, max_length=30)
    evidence_refs: list[EvidenceRefV12]
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def require_observational_evidence(self):
        if not self.log_templates and self.trace_summary is None:
            raise ValueError("A diagnostic snapshot requires log or trace observations")
        return self


class EvaluationLabelV12(StrictModel):
    schema_version: Literal[1] = 1
    event_id: str = Field(pattern=r"^evt_[A-Za-z0-9_-]+$")
    dataset: Literal["loghub_hadoop", "hdfs_v3_tracebench"]
    group_id: str
    split: Literal["development", "calibration", "independent_test"]
    anomaly_label: Literal["normal", "anomaly", "mixed"]
    injection_label: str | None
    root_cause_label: None = None
    metric_eligibility: MetricEligibilityV12


class AuthorizationV1(StrictModel):
    authorization_id: str = Field(min_length=1, max_length=128)
    approved_at: datetime
    retention_until: datetime
    deletion_contact: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def retention_after_approval(self):
        if self.retention_until <= self.approved_at:
            raise ValueError("retention_until must be after approved_at")
        return self


class IncidentTimestampsV1(StrictModel):
    fault_start: datetime | None
    first_observable_signal: datetime | None
    agent_detected: datetime | None
    human_confirmed: datetime | None
    recovered: datetime | None
    timezone_source: str | None = None

    @field_validator("fault_start", "first_observable_signal", "agent_detected",
                     "human_confirmed", "recovered")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Incident timestamps must include a timezone")
        return value


class IncidentEvidenceRefV1(StrictModel):
    ref_id: str
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    redaction_status: Literal["approved_redacted"]
    observed_at: datetime | None


class DiagnosisSnapshotRefV1(StrictModel):
    cutoff_time: datetime
    log_refs: list[IncidentEvidenceRefV1]
    metric_refs: list[IncidentEvidenceRefV1]
    ticket_refs: list[IncidentEvidenceRefV1]

    @field_validator("cutoff_time")
    @classmethod
    def cutoff_has_timezone(cls, value):
        if value.tzinfo is None:
            raise ValueError("cutoff_time must include a timezone")
        return value


class IncidentLabelsV1(StrictModel):
    root_cause_code: str | None
    confidence: Literal["confirmed", "high", "medium", "low", "unknown"]
    review_status: Literal["draft", "reviewed", "adjudicated", "unresolved"]
    evidence_refs: list[str]
    creator_id: str | None = None
    reviewer_id: str | None = None
    adjudicator_id: str | None = None


class IncidentRecordV1(StrictModel):
    schema_version: Literal[1]
    incident_id: str = Field(pattern=r"^inc_[A-Za-z0-9_-]{8,64}$")
    cluster_alias: str = Field(pattern=r"^cluster_[A-Za-z0-9_-]+$")
    product_version: str | None = Field(default=None, pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    fault_family: str | None = None
    authorization: AuthorizationV1
    timestamps: IncidentTimestampsV1
    diagnosis_snapshot: DiagnosisSnapshotRefV1
    labels: IncidentLabelsV1
