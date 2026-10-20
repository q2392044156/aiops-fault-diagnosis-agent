"""Opt-in LangChain and LangGraph adapters for parallel validation."""

from .report_chain import CandidateSummaryChain
from .retriever import LangChainRetrieverAdapter

__all__ = ["CandidateSummaryChain", "LangChainRetrieverAdapter"]
