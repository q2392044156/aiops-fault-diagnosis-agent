# detection

负责按来源 Drain3 模板和 severity-first 门禁。

| 文件 | 职责 |
| --- | --- |
| `__init__.py` | 导出 `TemplateNoveltyDetector`、`wilson` 和窗口 API。 |

实际实现位于 `src/aiops_diag/detection`；本目录作为离线检测层的稳定入口。
