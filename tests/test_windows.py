"""模块说明：验证独立的正常窗口加载。"""

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
