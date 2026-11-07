# diagnosis

负责单个 event 的 7 节点诊断。

| 文件 | 职责 |
| --- | --- |
| `__init__.py` | 导出 `AgentEngine`、`EvidenceSelector` 和兼容选择函数。 |

实际实现位于 `src/aiops_diag/diagnosis`；本目录作为在线诊断层的稳定入口。
