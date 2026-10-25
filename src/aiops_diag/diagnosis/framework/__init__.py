# 模块说明：定义当前包的公共入口、版本或导出符号。
"""Opt-in LangChain and LangGraph adapters for parallel validation."""

from .report_chain import CandidateSummaryChain
from .retriever import LangChainRetrieverAdapter

# 变量说明：`__all__` 保存本模块或数据模型使用的稳定值。
__all__ = ["CandidateSummaryChain", "LangChainRetrieverAdapter"]
