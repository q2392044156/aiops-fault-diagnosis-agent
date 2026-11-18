"""可选的 LangChain / LangGraph 适配层，用于并行验证。"""

from online.diagnosis.framework.report_chain import CandidateSummaryChain
from online.diagnosis.framework.retriever import LangChainRetrieverAdapter

__all__ = ["CandidateSummaryChain", "LangChainRetrieverAdapter"]
