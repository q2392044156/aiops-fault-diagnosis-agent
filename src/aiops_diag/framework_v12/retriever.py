"""LangChain view over the existing frozen and gated retriever."""

from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever


class LangChainRetrieverAdapter(BaseRetriever):
    """Expose the existing retriever without changing ranking or gate behavior.

    ``search`` remains the authoritative project API and returns its original
    envelope. LangChain's ``invoke`` returns only Documents, where an empty list
    represents the existing ``insufficient_evidence`` decision.
    """

    backend: Any
    mode: str | None = None
    top_k: int | None = None
    component: str | None = None
    product_version: str | None = None
    apply_gate: bool = True

    @property
    def manifest(self):
        return self.backend.manifest

    def verify_integrity(self):
        return self.backend.verify_integrity()

    def public(self):
        return self.backend.public()

    def chunk(self, chunk_id):
        return self.backend.chunk(chunk_id)

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

    def _get_relevant_documents(self, query: str, *, run_manager=None) -> list[Document]:
        return self.to_documents(self.search(query))

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
