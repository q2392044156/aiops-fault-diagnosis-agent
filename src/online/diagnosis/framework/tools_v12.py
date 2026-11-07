"""模块说明：v1.2 只读工具（Trace 能力已随 TraceBench 移除）。"""

from online.diagnosis.query_v11.tools import CandidateAgentTools


# 类说明：V12AgentTools 保留 v1.2 扩展点，当前不额外暴露 Trace 工具。
class V12AgentTools(CandidateAgentTools):
    pass
