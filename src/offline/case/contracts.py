"""
Strict contracts shared by the v1.2 public and real-incident data paths.

所有对外接口的输入输出格式都在这里以 Pydantic 模型的方式严格定义。
incident.py 依赖这里的模型做校验。
没有它，任何外部数据（无论是公共数据集的 JSONL 还是人工标注的 Incident JSON）都是不可信的

"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

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
