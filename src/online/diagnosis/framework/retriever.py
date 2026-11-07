# 模块说明：把现有混合检索器适配为 LangChain Retriever。
"""LangChain view over the existing frozen and gated retriever."""

from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever


# 类说明：`LangChainRetrieverAdapter` 封装本模块内聚的数据和行为。
class LangChainRetrieverAdapter(BaseRetriever):
    """Expose the existing retriever without changing ranking or gate behavior.

    ``search`` remains the authoritative project API and returns its original
    envelope. LangChain's ``invoke`` returns only Documents, where an empty list
    represents the existing ``insufficient_evidence`` decision.
    """

    # 变量说明：`backend` 保存本模块或数据模型使用的稳定值。
    backend: Any
    # 变量说明：`mode` 保存本模块或数据模型使用的稳定值。
    mode: str | None = None
    # 变量说明：`top_k` 保存本模块或数据模型使用的稳定值。
    top_k: int | None = None
    # 变量说明：`component` 保存本模块或数据模型使用的稳定值。
    component: str | None = None
    # 变量说明：`product_version` 保存本模块或数据模型使用的稳定值。
    product_version: str | None = None
    # 变量说明：`apply_gate` 保存本模块或数据模型使用的稳定值。
    apply_gate: bool = True

    # 方法说明：`manifest` 完成当前步骤的业务处理；参数为 无显式业务参数。
    @property
    def manifest(self):
        return self.backend.manifest

    # 方法说明：`verify_integrity` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def verify_integrity(self):
        return self.backend.verify_integrity()

    # 方法说明：`public` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def public(self):
        return self.backend.public()

    # 方法说明：`chunk` 完成当前步骤的业务处理；参数为 `chunk_id`。
    def chunk(self, chunk_id):
        return self.backend.chunk(chunk_id)

    # 方法说明：`search` 完成当前步骤的业务处理；参数为 `query`、`mode`、`top_k`、`component`、`product_version`、`apply_gate`。
    def search(self, query, mode=None, top_k=None, component=None,
               product_version=None, apply_gate=None):
        return self.backend.search(
            query,
            mode=self.mode if mode is None else mode,
            top_k=self.top_k if top_k is None else top_k,
            component=self.component if component is None else component,
            product_version=(self.product_version if product_version is None
                             else product_version),
            apply_gate=self.apply_gate if apply_gate is None else apply_gate,
        )

    # 方法说明：`_get_relevant_documents` 完成当前步骤的业务处理；参数为 `query`、`run_manager`。
    def _get_relevant_documents(self, query: str, *, run_manager=None) -> list[Document]:
        return self.to_documents(self.search(query))

    # 方法说明：`to_documents` 完成当前步骤的业务处理；参数为 `result`。
    def to_documents(self, result: dict) -> list[Document]:
        release = self.manifest
        common = {
            "retrieval_status": result.get("status"),
            "retrieval_mode": result.get("mode"),
            "gate_score": result.get("gate_score"),
            "gate_strategy": result.get("gate_strategy"),
            "kb_release_id": release.get("kb_release_id"),
            "corpus_hash": release.get("corpus_hash"),
            "index_hash": release.get("index_hash"),
            "model_hash": release.get("model_hash"),
        }
        documents = []
        for item in result.get("items", []):
            metadata = {name: value for name, value in item.items() if name != "text"}
            metadata.update(common)
            documents.append(Document(page_content=item.get("text", ""),
                                      metadata=metadata))
        return documents
