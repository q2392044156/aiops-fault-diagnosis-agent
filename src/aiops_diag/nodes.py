"""诊断节点的固定推进顺序；在线引擎用它排序，离线评测用它算"走到了第几步"。"""

NODE_ORDER: dict[str, int] = {
    "RECEIVED": 0, "VALIDATED": 1, "DETECTED": 2, "EVIDENCE_COLLECTED": 3,
    "RETRIEVED": 4, "HYPOTHESES_RANKED": 5, "REPORT_VALIDATED": 6,
}
