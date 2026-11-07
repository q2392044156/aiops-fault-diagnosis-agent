"""模块说明：检测、事件、证据和引用评测脚本索引。"""

# 变量说明：EVALUATORS 指向离线评测脚本。
EVALUATORS = {
    "windows": "ops/scripts/evaluate_windows.py",
    "events": "ops/scripts/evaluate_events.py",
    "evidence": "ops/scripts/evaluate_evidence.py",
    "citations": "ops/scripts/evaluate_citations.py",
    "merge": "ops/scripts/merge_evaluations.py",
}

# 变量说明：__all__ 导出本流程的公共入口。
__all__ = ["EVALUATORS"]
