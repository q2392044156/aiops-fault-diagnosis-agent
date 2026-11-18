"""多格式日志接入、规范化与滑动窗口。"""

from offline.ingestion.adapters import parse_container, parse_hdfs_v1, parse_line, parse_lines
from offline.ingestion.canonical import canonical_log, is_parsed
from offline.ingestion.windows import load_case_windows, load_normal_windows, make_windows

# __all__ 导出本流程的公共入口。
__all__ = [
    "parse_container", "parse_hdfs_v1", "parse_line", "parse_lines",
    "canonical_log", "is_parsed",
    "load_case_windows", "load_normal_windows", "make_windows",
]
