"""模块说明：定义当前模块输入输出的 Pydantic 数据结构。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# 类说明：`StrictModel` 封装本模块内聚的数据和行为。
class StrictModel(BaseModel):
    # 变量说明：`model_config` 保存本模块或数据模型使用的稳定值。
    model_config = ConfigDict(extra="forbid")


# 类说明：`EvidenceClaim` 封装本模块内聚的数据和行为。
class EvidenceClaim(StrictModel):
    # 变量说明：`claim` 保存本模块或数据模型使用的稳定值。
    claim: str = Field(min_length=1, max_length=800)
    # 变量说明：`chunk_ids` 保存本模块或数据模型使用的稳定值。
    chunk_ids: list[str] = Field(min_length=1, max_length=5)


# 类说明：`RecommendedCheck` 封装本模块内聚的数据和行为。
class RecommendedCheck(StrictModel):
    # 变量说明：`action` 保存本模块或数据模型使用的稳定值。
    action: str = Field(min_length=1, max_length=800)
    # 变量说明：`rationale` 保存本模块或数据模型使用的稳定值。
    rationale: str = Field(min_length=1, max_length=800)
    # 变量说明：`chunk_ids` 保存本模块或数据模型使用的稳定值。
    chunk_ids: list[str] = Field(min_length=1, max_length=5)
    # 变量说明：`risk` 保存本模块或数据模型使用的稳定值。
    risk: str = Field(min_length=1, max_length=500)


# 类说明：`GeneratedBody` 封装本模块内聚的数据和行为。
class GeneratedBody(StrictModel):
    # 变量说明：`summary` 保存本模块或数据模型使用的稳定值。
    summary: str = Field(min_length=1, max_length=1200)
    # 变量说明：`evidence_claims` 保存本模块或数据模型使用的稳定值。
    evidence_claims: list[EvidenceClaim] = Field(max_length=12)
    # 变量说明：`recommended_checks` 保存本模块或数据模型使用的稳定值。
    recommended_checks: list[RecommendedCheck] = Field(max_length=12)
    # 变量说明：`missing_information` 保存本模块或数据模型使用的稳定值。
    missing_information: list[str] = Field(max_length=12)
    # 变量说明：`limitations` 保存本模块或数据模型使用的稳定值。
    limitations: list[str] = Field(min_length=1, max_length=12)


# 类说明：`EvidenceReference` 封装本模块内聚的数据和行为。
class EvidenceReference(StrictModel):
    # 变量说明：`chunk_id` 保存本模块或数据模型使用的稳定值。
    chunk_id: str
    # 变量说明：`title` 保存本模块或数据模型使用的稳定值。
    title: str
    # 变量说明：`section_path` 保存本模块或数据模型使用的稳定值。
    section_path: str
    # 变量说明：`evidence_url` 保存本模块或数据模型使用的稳定值。
    evidence_url: str
    # 变量说明：`source_url` 保存本模块或数据模型使用的稳定值。
    source_url: str | None = None


# 类说明：`Provenance` 封装本模块内聚的数据和行为。
class Provenance(StrictModel):
    # 变量说明：`rag_version` 保存本模块或数据模型使用的稳定值。
    rag_version: str
    # 变量说明：`kb_release_id` 保存本模块或数据模型使用的稳定值。
    kb_release_id: str
    # 变量说明：`retrieval_mode` 保存本模块或数据模型使用的稳定值。
    retrieval_mode: str
    # 变量说明：`provider` 保存本模块或数据模型使用的稳定值。
    provider: str | None
    # 变量说明：`model` 保存本模块或数据模型使用的稳定值。
    model: str | None
    # 变量说明：`prompt_version` 保存本模块或数据模型使用的稳定值。
    prompt_version: str
    # 变量说明：`query_hash` 保存本模块或数据模型使用的稳定值。
    query_hash: str
    # 变量说明：`evidence_chunk_ids` 保存本模块或数据模型使用的稳定值。
    evidence_chunk_ids: list[str]
    # 变量说明：`generated_at` 保存本模块或数据模型使用的稳定值。
    generated_at: str
    # 变量说明：`input_tokens` 保存本模块或数据模型使用的稳定值。
    input_tokens: int = 0
    # 变量说明：`output_tokens` 保存本模块或数据模型使用的稳定值。
    output_tokens: int = 0
    # 变量说明：`estimated_cost_cny` 保存本模块或数据模型使用的稳定值。
    estimated_cost_cny: float = 0.0


# 类说明：`RagReport` 封装本模块内聚的数据和行为。
class RagReport(StrictModel):
    # 变量说明：`schema_version` 保存本模块或数据模型使用的稳定值。
    schema_version: int = 1
    # 变量说明：`report_id` 保存本模块或数据模型使用的稳定值。
    report_id: str
    # 变量说明：`status` 保存本模块或数据模型使用的稳定值。
    status: Literal["EVIDENCE_SUPPORTED", "INSUFFICIENT_EVIDENCE", "DEGRADED_TEMPLATE"]
    # 变量说明：`summary` 保存本模块或数据模型使用的稳定值。
    summary: str
    # 变量说明：`evidence_claims` 保存本模块或数据模型使用的稳定值。
    evidence_claims: list[EvidenceClaim]
    # 变量说明：`recommended_checks` 保存本模块或数据模型使用的稳定值。
    recommended_checks: list[RecommendedCheck]
    # 变量说明：`missing_information` 保存本模块或数据模型使用的稳定值。
    missing_information: list[str]
    # 变量说明：`limitations` 保存本模块或数据模型使用的稳定值。
    limitations: list[str]
    # 变量说明：`requires_review` 保存本模块或数据模型使用的稳定值。
    requires_review: bool = True
    # 变量说明：`evidence` 保存本模块或数据模型使用的稳定值。
    evidence: list[EvidenceReference]
    # 变量说明：`provenance` 保存本模块或数据模型使用的稳定值。
    provenance: Provenance
    # 变量说明：`report_hash` 保存本模块或数据模型使用的稳定值。
    report_hash: str
