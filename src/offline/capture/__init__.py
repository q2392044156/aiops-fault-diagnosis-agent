"""模块说明：故障注入与日志采集入口。"""

# 变量说明：CAPTURE_COMMANDS 指向现有采集脚本，保持兼容。
CAPTURE_COMMANDS = {
    "docker": "ops/lab/harness/run_case.py",
    "wsl": "ops/lab/wsl/run_case.py",
    "batch": "ops/lab/harness/run_batch.py",
}

# 变量说明：__all__ 导出本流程的公共入口。
__all__ = ["CAPTURE_COMMANDS"]
