# 项目文档索引

> 当前版本：v1.2 RC1（1.2.0rc1）+ 路线 A 真实故障实验。
> 本页是文档导航；**最新数字以本页与根 README 为准**，历史报告保留当时的冻结口径，不再回写。

## 1. 当前结论（优先看）

| 文档 | 内容 |
| --- | --- |
| [路线A_最终报告.md](路线A_最终报告.md) | 一页版：WSL 68 / Docker 81、Top-1/Top-3/Top-5、失败归因、边界 |
| [路线A_WSL与Docker对比.md](路线A_WSL与Docker对比.md) | 两套实验台的差异、为什么不能相加、环境边界 |
| [../resources/evaluation/lab/failure_attribution.md](../resources/evaluation/lab/failure_attribution.md) | Docker 81 例归因：74 命中 / 5 证据 / 0 召回 / 2 排序 |
| [../resources/evaluation/lab/wsl.md](../resources/evaluation/lab/wsl.md) | WSL 68 例指标 |
| [../resources/evaluation/lab/real_batch.md](../resources/evaluation/lab/real_batch.md) | Docker 81 例指标 |

当前关键数字：

| 实验台 | 样本 | Top-1 | 冻结测试集 |
| --- | --- | --- | --- |
| WSL（1NN+1DN） | 68 | 100%（CI [0.9465, 1.0]） | n=14，100% |
| Docker（1NN+3DN） | 81 | 91.4%（CI [0.8322, 0.9575]） | n=30，90% |

## 2. 能力报告（P0-1 ～ P2-6）

| 能力 | 文档 |
| --- | --- |
| P0-1 工具路由 | [P0-1_工具路由.md](P0-1_工具路由.md) |
| P0-2 轨迹评测 | [P0-2_轨迹评测.md](P0-2_轨迹评测.md) |
| P0-3 上下文工程 | [P0-3_上下文工程.md](P0-3_上下文工程.md) |
| P1-4 可观测性 | [P1-4_可观测性.md](P1-4_可观测性.md) |
| P1-5 红队评测 | [P1-5_红队评测.md](P1-5_红队评测.md) |
| P2-6 MCP 服务 | [P2-6_MCP服务.md](P2-6_MCP服务.md) |

## 3. 架构与结构

| 文档 | 内容 |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 分层、模块边界、四条不变量 |
| [../PROJECT_STRUCTURE.md](../PROJECT_STRUCTURE.md) | 目录结构、依赖方向、兼容约定 |
| [architecture.png](architecture.png) / [architecture.svg](architecture.svg) | 架构图 |

## 4. 数据调研

| 文档 | 内容 |
| --- | --- |
| [真实根因数据调研与替代方案.md](真实根因数据调研与替代方案.md) | 公开 HDFS 数据是否有真实根因标签，以及三条替代路线 |
| [路线A_MVP.md](路线A_MVP.md) | 路线 A 的方法、实验台、指标口径与边界 |

## 5. 历史版本（保留，不代表当前）

以下报告记录当时的冻结状态与验收结论，数字与结论不要与当前结果混用：

- [v1.2_RC1_实施报告.md](v1.2_RC1_实施报告.md)
- [AIOps_v1.0_技术报告.md](AIOps_v1.0_技术报告.md)
- [v1_acceptance.md](v1_acceptance.md)
- [v1_1_candidate_report.md](v1_1_candidate_report.md)
- [framework_rc2_acceptance_report.md](framework_rc2_acceptance_report.md)
- [framework_candidate_report.md](framework_candidate_report.md)

## 6. 结果与本地资料

- `results/`：与历史报告对应的机器可读结果；
- `archive/`：W1–W9 早期产物，本地忽略，仅供追溯；
- 演示 PPT、面试笔记等文件由 `.gitignore` 忽略，只保留在本地；
- 实验数据集（`ops/lab/*_cases/`）不随仓库分发，按 README 命令本地生成。

## 7. 约定

1. **数字口径**：当前只认"严格代码级根因码"；组件级匹配、历史 85.4% 等不再作为成绩；
2. **两套实验不相加**：WSL 与 Docker 的注入形态、拓扑、样本量不同；
3. **历史不改写**：旧报告保留原数字，新结论写入根 README 与路线 A 报告；
4. **复现优先**：结构完整性以 `python ops/scripts/validate_project_structure.py` 为准。
