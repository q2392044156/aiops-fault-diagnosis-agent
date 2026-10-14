from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceClaim(StrictModel):
    claim: str = Field(min_length=1, max_length=800)
    chunk_ids: list[str] = Field(min_length=1, max_length=5)


class RecommendedCheck(StrictModel):
    action: str = Field(min_length=1, max_length=800)
    rationale: str = Field(min_length=1, max_length=800)
    chunk_ids: list[str] = Field(min_length=1, max_length=5)
    risk: str = Field(min_length=1, max_length=500)


class GeneratedBody(StrictModel):
    summary: str = Field(min_length=1, max_length=1200)
    evidence_claims: list[EvidenceClaim] = Field(max_length=12)
    recommended_checks: list[RecommendedCheck] = Field(max_length=12)
    missing_information: list[str] = Field(max_length=12)
    limitations: list[str] = Field(min_length=1, max_length=12)


class EvidenceReference(StrictModel):
    chunk_id: str
    title: str
    section_path: str
    evidence_url: str
    source_url: str | None = None


class Provenance(StrictModel):
    rag_version: str
    kb_release_id: str
    retrieval_mode: str
    provider: str | None
    model: str | None
    prompt_version: str
    query_hash: str
    evidence_chunk_ids: list[str]
    generated_at: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_cny: float = 0.0


class RagReport(StrictModel):
    schema_version: int = 1
    report_id: str
    status: Literal["EVIDENCE_SUPPORTED", "INSUFFICIENT_EVIDENCE", "DEGRADED_TEMPLATE"]
    summary: str
    evidence_claims: list[EvidenceClaim]
    recommended_checks: list[RecommendedCheck]
    missing_information: list[str]
    limitations: list[str]
    requires_review: bool = True
    evidence: list[EvidenceReference]
    provenance: Provenance
    report_hash: str
