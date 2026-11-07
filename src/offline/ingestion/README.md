# ingestion

负责多格式日志接入、规范化和窗口化。

| 文件 | 职责 |
| --- | --- |
| `__init__.py` | 导出 adapter、canonical、window API。 |

实际实现位于 `src/aiops_diag/data`；本目录作为离线接入层的稳定入口。
