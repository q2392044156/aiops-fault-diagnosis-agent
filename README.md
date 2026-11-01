# AIOps Fault Diagnosis Agent

[![ci](https://github.com/q2392044156/aiops-fault-diagnosis-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/q2392044156/aiops-fault-diagnosis-agent/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

面向 HDFS 日志与调用链的故障诊断研究原型。它不追求"让大模型自动修机器"，而是回答一个更实际的问题：**当系统异常时，如何把海量日志压缩成可核查的事件，再结合冻结版本的运维知识，给出带证据、可追溯、可人工复核的诊断报告。**

系统遵守两条硬边界：

1. 只给异常线索、证据引用和只读排查建议，**不执行**重启、删除、切流、写库；所有建议固定 `execution_allowed=false`。
2. 没有合格真实根因标签时，不把公开故障注入标签包装成生产根因，也不虚报 Top-1 与 MTTD。

当前版本 **v1.2 RC1**（`1.2.0rc1`），含路线 A 真实故障实验。

---

## 最新结果

| 实验台 | 样本 | Top-1 | Top-3 | Top-5 | 冻结测试集 |
| --- | --- | --- | --- | --- | --- |
| WSL 单机（Hadoop 3.3.6） | 68（38 卷 + 10 心跳 + 20 安全模式） | **100%**（CI [0.9465, 1.0]） | 100% | 100% | n=14，100% |
| Docker Compose（1NN+3DN） | 81（28 卷 + 27 心跳 + 26 安全模式） | **72.8%**（CI [0.6228, 0.8133]） | 92.6% | 93.8% | n=30，70.0% |

Docker 81 例失败归因：**命中 59、证据缺失 5、召回缺失 0、排序错误 17**——心跳已全部修复，剩余短板是卷满排序。

六项工程能力（每项都有代码、单测与数字）：

| 能力 | 关键结果 |
| --- | --- |
| P0-1 工具路由 | 规则 93.3% > 受控 90.0% > 自由 66.7%；受控参数 100% 结构化 |
| P0-2 轨迹评测 | 30 例封存：18 clean + 12 abstained，0 重试、0 越权引用 |
| P0-3 上下文工程 | 压缩省 36.5% token，Schema/引用/双类证据持平 |
| P1-4 可观测性 | 单次诊断 29 个 span，6.73s 中 6.59s 在生成 |
| P1-5 红队 | 40/40 拦截（100%），0/10 误杀 |
| P2-6 MCP | 5 个只读工具，initialize/list/call 冒烟通过 |

> 两套实验数字**不能相加**：注入形态、拓扑、样本量都不同。

---

## 系统如何工作

![架构总览](documentation/architecture.png)

```text
HDFS 日志 / 聚合 Trace
          ↓
数据校验、脱敏、稳定分组切分
          ↓
冻结 Drain3 + TF-IDF/LR 异常检测
          ↓
确定性查询构建 ──→ BM25 + BGE ONNX + RRF 知识检索
          ↓                         ↓
只读日志 / Trace 工具          固定版本知识证据
          └──────────┬──────────────┘
                     ↓
         确定性 Agent 状态机 + SQLite 状态
                     ↓
         结构化报告 / 安全模板降级
                     ↓
              人工复核与审计留痕
```

Agent 节点固定：`RECEIVED → VALIDATED → DETECTED → EVIDENCE_COLLECTED → RETRIEVED → HYPOTHESES_RANKED → REPORT_VALIDATED`。预算：8 次工具调用、3 次 LLM 调用、12k token、120s、最多 2 次修订。

三个服务：

- `api`：接收批次、创建诊断、查询事件/报告/工具调用、处理人工审批；
- `worker`：执行检测、检索、Agent 工作流与报告生成；
- `ui`：Streamlit 复核台。

SQLite 是任务、预算、工具缓存、报告、审批与审计的业务真相源；checkpoint 只保存流程恢复需要的图状态。

底层模型基线（冻结）：

| 组件 | 指标 |
| --- | --- |
| 异常检测（TF-IDF + LR） | F1 0.883181、AP 0.789731、FPR 0.006374 |
| 知识检索（Hybrid Top-3） | Recall 0.975、MRR 0.9375、nDCG 0.7827 |

完整分层与四条不变量见 [ARCHITECTURE.md](documentation/ARCHITECTURE.md)。

---

## 快速开始（Demo，约 5 分钟，无需 API Key）

仓库内置离线端到端演示：一条 HDFS 日志 → 异常会话 → 事件 → 受控诊断 → 带引用的报告 → 人工复核，全程约 1 秒。

```powershell
conda activate aiops-fault-diagnosis-agent
python demo/run_demo.py            # 离线，不花钱
python demo/run_demo.py --online   # 在线，单次约 ¥0.03（需 DEEPSEEK_API_KEY）
```

预期看到：`diagnosis_status`、`final_status=APPROVED_REPORT`、工具调用次数与报告引用。

- 3 分钟演示脚本：[demo/README.md](demo/README.md)
- 全量测试与结构校验：

```powershell
python -m pytest -q --basetemp=.pytest-tmp
python ops/scripts/validate_project_structure.py
```

> Windows 上若默认临时目录不可写，保留 `--basetemp=.pytest-tmp`。

---

## 完整复现

### 1. 安装

要求 Python 3.11（`>=3.11,<3.12`）、Conda（推荐）、Docker（仅容器实验需要）。

```powershell
conda env create --file environment.yml
conda run --name aiops-fault-diagnosis-agent python -m pip install -r requirements-framework-lock.txt
conda run --name aiops-fault-diagnosis-agent python -m pip install -e ".[dev,research,framework]" --no-deps
conda run --name aiops-fault-diagnosis-agent python -m pip check
```

### 2. 测试与校验

```powershell
conda run --name aiops-fault-diagnosis-agent python -m pytest -q --basetemp=.pytest-tmp
conda run --name aiops-fault-diagnosis-agent python ops/scripts/validate_project_structure.py
```

### 3. 路线 A：WSL 单机（推荐，故障更真实）

依赖 WSL2 + Ubuntu + JDK 11 + Hadoop 3.3.6，数据目录是 64MB ext4 loop 镜像。

```bash
bash ops/lab/wsl/readonly_volume.sh
python ops/lab/wsl/run_case.py --fault DN_VOLUME --database runtime/lab/wsl.sqlite3
python ops/lab/wsl/run_case.py --fault DN_HEARTBEAT --database runtime/lab/wsl.sqlite3
python ops/lab/wsl/run_case.py --fault NN_SAFE_MODE --database runtime/lab/wsl.sqlite3
python ops/scripts/evaluate_incidents.py --database runtime/lab/wsl.sqlite3 --cases ops/lab/wsl_cases
```

说明与安装步骤见 [ops/lab/wsl/README.md](ops/lab/wsl/README.md)。

### 4. 路线 A：Docker Compose（规模化，环境受限）

```powershell
docker compose -f ops/lab/compose.yaml up -d
python ops/lab/harness/run_batch.py --real --per-fault 7 --observe 12 --database runtime/lab/real_batch.sqlite3
python ops/scripts/evaluate_incidents.py --database runtime/lab/real_batch.sqlite3 --cases ops/lab/real_batch_cases
docker compose -f ops/lab/compose.yaml down -v
```

### 5. 评测、红队与 MCP

```powershell
python ops/scripts/evaluate_router.py
python ops/scripts/evaluate_trajectory.py --database runtime/v12/service.sqlite3
python ops/scripts/evaluate_context.py --database runtime/v12/service.sqlite3
python ops/scripts/run_redteam.py
python ops/scripts/attribute_failures.py --database runtime/lab/real_batch.sqlite3 --cases ops/lab/real_batch_cases --output resources/evaluation/lab/failure_attribution
python ops/scripts/mcp_smoke.py
```

路由与上下文消融需要 `DEEPSEEK_API_KEY`；其余可离线运行。

### 6. 数据与制品

`data/`、`artifacts/`、`experiments/`、`runtime/`、`ops/lab/*_cases/` 均不提交 Git，需在本地生成。密钥只放在 `.env`（已忽略），示例见 [.env.example](.env.example)。

---

## 目录结构

```text
aiops-fault-diagnosis-agent/
├─ src/aiops_diag/
│  ├─ data/          # 接入、脱敏、审计与标准化
│  ├─ detection/     # LR/LSTM 检测
│  ├─ knowledge/     # BM25/BGE/RRF 检索与报告生成
│  ├─ diagnosis/     # Agent、路由、工具与编排
│  ├─ evaluation/    # 轨迹、路由、红队评测
│  ├─ platform/      # FastAPI、worker、SQLite、Streamlit、MCP
│  └─ release/       # 发布冻结与导出
├─ resources/        # 配置、知识卡、评测结果
├─ ops/              # 实验台、脚本与红队用例
├─ documentation/    # 报告、架构与验收记录
├─ tests/            # 自动化测试
├─ demo/             # 离线端到端演示
├─ Makefile
├─ LICENSE
└─ pyproject.toml
```

依赖方向与模块边界见 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)，每个源码目录有独立 `README.md`。

---

## 文档索引

| 内容 | 路径 |
| --- | --- |
| 一页版路线 A 最终报告 | [documentation/路线A_最终报告.md](documentation/路线A_最终报告.md) |
| WSL / Docker 对比 | [documentation/路线A_WSL与Docker对比.md](documentation/路线A_WSL与Docker对比.md) |
| 失败归因 | [resources/evaluation/lab/failure_attribution.md](resources/evaluation/lab/failure_attribution.md) |
| WSL 指标 | [resources/evaluation/lab/wsl.md](resources/evaluation/lab/wsl.md) |
| Docker 指标 | [resources/evaluation/lab/real_batch.md](resources/evaluation/lab/real_batch.md) |
| 工具路由 | [documentation/P0-1_工具路由.md](documentation/P0-1_工具路由.md) |
| 轨迹评测 | [documentation/P0-2_轨迹评测.md](documentation/P0-2_轨迹评测.md) |
| 上下文工程 | [documentation/P0-3_上下文工程.md](documentation/P0-3_上下文工程.md) |
| 可观测性 | [documentation/P1-4_可观测性.md](documentation/P1-4_可观测性.md) |
| 红队 | [documentation/P1-5_红队评测.md](documentation/P1-5_红队评测.md) |
| MCP | [documentation/P2-6_MCP服务.md](documentation/P2-6_MCP服务.md) |
| 架构 | [documentation/ARCHITECTURE.md](documentation/ARCHITECTURE.md) |

---

## 边界与已知限制

- **真实数据仍偏窄**：只有 3 个根因码、实验室注入，不是生产工单；
- **Docker 指标仍有提升空间**：Top-1 72.8%，主要受卷满排序拖累；
- **WSL 100% 有天花板效应**：单机、单形态、测试集 14 例；
- **MTTD 不可用**：Docker 含观测窗，WSL 未落库；
- **未覆盖**：真实 ENOSPC、IO error、网络分区、HA、NameNode 不可用、多故障叠加；
- **不是独立盲测**：同一脚本、同一机器生成。

这些问题在 [路线A_最终报告.md](documentation/路线A_最终报告.md) 中有完整说明。

---

## License

MIT，见 [LICENSE](LICENSE)。
