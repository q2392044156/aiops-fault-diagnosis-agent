"""模块说明：按来源模板和 severity-first 门禁的异常检测。"""

from offline.ingestion.windows import load_case_windows, load_normal_windows, make_windows
from offline.detection.source_detector import TemplateNoveltyDetector, wilson

# 变量说明：__all__ 导出本流程的公共入口。
__all__ = [
    "TemplateNoveltyDetector", "wilson",
    "load_case_windows", "load_normal_windows", "make_windows",
]
