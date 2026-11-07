"""模块说明：验证统一时间/组件窗口。"""

from aiops_diag.data.windows import make_windows
from ops.lab.harness.windows import load_normal_windows


# 方法说明：验证正常日志按行窗口切分。
def test_normal_windows_split_by_lines(tmp_path):
    log = tmp_path / "normal.log"
    lines = [f"[dn1] 2026-10-28 12:00:{index:02d} INFO  DataNode:1 - ok"
             for index in range(120)]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    windows = load_normal_windows(tmp_path, "docker_container", window_lines=50)
    assert len(windows) == 3
    assert [len(window) for window in windows] == [50, 50, 20]


# 方法说明：验证统一窗口按组件和时间桶切分。
def test_make_windows_uses_time_and_component():
    rows = [
        {"timestamp_utc": "2026-10-28T12:00:00+00:00", "component": "DataNode",
         "level": "INFO", "message": "a"},
        {"timestamp_utc": "2026-10-28T12:00:30+00:00", "component": "DataNode",
         "level": "INFO", "message": "b"},
        {"timestamp_utc": "2026-10-28T12:01:10+00:00", "component": "DataNode",
         "level": "INFO", "message": "c"},
        {"timestamp_utc": "2026-10-28T12:00:00+00:00", "component": "NameNode",
         "level": "INFO", "message": "d"},
    ]
    windows = make_windows(rows, "docker_container", duration_seconds=60,
                           step_seconds=10, max_rows=500)
    assert len(windows) == 9
    assert {window["component"] for window in windows} == {"DataNode", "NameNode"}
    assert any(window["line_count"] == 2 for window in windows)
    assert sum(1 for window in windows
               if any(row["message"] == "b" for row in window["rows"])) > 1


# 方法说明：验证超长窗口按最大行数切分。
def test_make_windows_caps_rows():
    rows = [{"timestamp_utc": "2026-10-28T12:00:00+00:00", "component": "DataNode",
             "level": "INFO", "message": str(index)} for index in range(5)]
    windows = make_windows(rows, "docker_container", duration_seconds=60, max_rows=2)
    assert [window["line_count"] for window in windows] == [2, 2, 1]
