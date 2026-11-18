"""v1.2 只读工具扩展点；Trace 能力已随 TraceBench 移除。"""

from online.diagnosis.tools import CandidateAgentTools


# CheckpointTools 保留 v1.2 扩展点，当前不额外暴露 Trace 工具。
class CheckpointTools(CandidateAgentTools):
    pass
