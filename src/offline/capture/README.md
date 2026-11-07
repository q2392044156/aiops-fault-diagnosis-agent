# capture

负责故障注入和日志采集。

| 文件 | 职责 |
| --- | --- |
| `__init__.py` | 导出 Docker/WSL/批量采集入口索引 `CAPTURE_COMMANDS`。 |

采集脚本仍位于 `ops/lab/harness` 和 `ops/lab/wsl`，避免破坏已有实验入口。
