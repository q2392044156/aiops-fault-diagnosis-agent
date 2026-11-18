"""按来源模板和 severity-first 门禁的异常检测。"""

from offline.detection.novelty import TemplateNoveltyDetector, wilson
from offline.ingestion.windows import load_case_windows, load_normal_windows, make_windows

# __all__ 导出本流程的公共入口。
__all__ = [
    "TemplateNoveltyDetector", "wilson",
    "load_case_windows", "load_normal_windows", "make_windows",
]
