# 项目文档

本目录统一保存不参与 Python 运行的说明和验收资料：

- 根目录下的 Markdown 文件是版本报告、候选说明和验收结论。
- `results/` 保存与报告对应的机器可读历史结果。
- `archive/` 保存早期 W1–W9 阶段产物；该目录由 `.gitignore` 忽略，仅供本地追溯。
- 演示文件、面试笔记和 demo 资料继续保持本地忽略，不进入发布制品。

历史验收清单中的路径和哈希用于说明当时的冻结状态。源码目录重构后，不应覆盖或重写这些历史结论；当前结构完整性请运行：

```powershell
python ops/scripts/validate_project_structure.py
```
