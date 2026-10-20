# AIOps Fault Diagnosis Agent

面向公开 HDFS 日志的可复现、可追溯故障诊断研究原型。项目从 1117 万行日志出发，依次完成数据协议、异常检测、知识检索、证据约束报告、受控 Agent、人工复核和 CPU 容器部署。**v1.0** 仍是已发布基线；当前默认研究后端是 **v1.1 Framework RC2**，使用确定性查询构建、LangChain 与 LangGraph，并保留 legacy 一键回退。

系统只提供异常线索、引用证据和只读排查建议。HDFS_v1 没有真实根因标签，因此不报告“根因准确率”；所有建议固定 `execution_allowed=false`，审批只代表报告被人工审核，不会执行重启、删除、切流或写库。

## 结果摘要

| 项目 | 冻结结果 |
|---|---|
| 数据 | 11,175,629 行；575,061 个 block 会话；16,838 个异常会话 |
| 默认检测模型 | TF-IDF + Logistic Regression，测试 F1 `0.883181`、AP `0.789731`、FPR `0.006374` |
| 研究对照 | LSTM 三 seed 测试 F1 `0.883363 ± 0.000708`、AP `0.974166 ± 0.020106` |
| 知识检索 | Hybrid Top-3；Rtest Recall `0.975`、MRR `0.9375`、nDCG `0.7827` |
| W10 Atest | 40 例 × 3 次真实 DeepSeek；Task Success、强制复核 Recall、引用合法率均为 `100%` |
| 报告稳定性 | Schema 通过率 `93.33% ± 11.55%`；模板降级率 `6.67% ± 11.55%` |
| W10 在线成本 | 115,976 输入 tokens、17,104 输出 tokens，估算 `¥0.426384` |
| v1.0 工程验收 | 100 项测试通过；全新 Python 3.11.17 环境与无缓存 Compose 验收通过 |
| v1.1 Framework RC2 | 全量 158 项测试通过；真实索引开发集 12/12；在线 DeepSeek 18/18；封存集 30/30；安全硬门禁均为 0 |

模型测试指标来自冻结测试集的一次性评测。检索 Rtest 无答案误返回率为 20%，高于 Rdev 的 10%，未使用测试结果反向调参。W9 的 LLM 可选工具路由准确率仅 55%，低于 80% 门槛，v1.0 因而保持关闭，由确定性状态机控制工具。

## 架构

```text
HDFS 日志 → 流式解析 / block 会话 → 冻结 Drain3 → TF-IDF + LR
                                             ↓ 异常事件
原创知识卡片 → BM25 + BGE ONNX + RRF → 受控 Agent → 证据报告
                                             ↓
                                      人工复核（不执行动作）
```

Compose 固定三个服务：`api` 负责接入与查询，`worker` 负责检测和 Agent 状态机，`ui` 提供 Streamlit 复核台。SQLite WAL、任务租约、幂等键和原子发布支持单机恢复；模型、知识库与密钥均采用只读挂载。

## 快速开始

唯一支持的研究环境为 Python 3.11 的 Conda 环境 `aiops-fault-diagnosis-agent`：

```powershell
conda env create --file environment.yml
conda run --name aiops-fault-diagnosis-agent python -m pip install -r requirements-lock.txt
conda run --name aiops-fault-diagnosis-agent python -m pip install -e ".[dev,research]" --no-deps
conda run --name aiops-fault-diagnosis-agent python -m pip check
conda run --name aiops-fault-diagnosis-agent python -m pytest -q
```

发布并启动 CPU 服务：

```powershell
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.service publish --config configs/service.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.service verify --config configs/service.yaml
docker compose -f deployment/compose.yaml up --build -d
```

- OpenAPI：`http://127.0.0.1:8000/docs`
- Streamlit：`http://127.0.0.1:8501`
- 在线 DeepSeek：显式追加 `-f deployment/compose.online.yaml`；默认离线模板模式不消耗 Token。
- 端口被占用时可设置 `AIOPS_API_BIND=127.0.0.1:18000`、`AIOPS_UI_BIND=127.0.0.1:18501`。

运行时不下载模型、不训练模型、不搜索阈值。镜像使用非 root UID 10001、只读根文件系统、删除全部 capabilities、启用 `no-new-privileges`，不含 Torch/CUDA，也不挂载 Docker socket。

## 复现实验

数据、建模、检索、RAG 和 Agent 均提供模块化 CLI；常用入口如下：

```powershell
# W1 数据
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.data audit --config configs/data.yaml

# W2/W3 模型
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.modeling run --config configs/model_lr.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.modeling lstm-run --config configs/model_lstm.yaml

# W4 一次性测试入口
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.selection finalize --config configs/model_selection.yaml --device auto

# W7/W8
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.retrieval verify --config configs/retrieval.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.rag verify --config configs/rag.yaml

# W9/W10 Agent 评测
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.agent evaluate --config configs/agent.yaml --suite atest --mode replay
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.agent evaluate --config configs/agent.yaml --suite atest --mode online --repeat 3

# v1.0 发布
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.release freeze --config configs/release.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.release verify --config configs/release.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.release accept --config configs/release.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.release export --config configs/release.yaml
```

`finalize` 和 W10 在线评测均有冻结哈希、幂等与预算门禁。修改测试协议、源码或上游发布制品后，候选校验会失败。

## v1.1 Framework RC2

RC2 保留 BM25、BGE ONNX、RRF、证据门禁和 SQLite 权威状态。新增的确定性 `RetrievalQueryBuilder` 从脱敏组件、等级、版本和白名单信号构建最多三个检索计划；LangChain 负责检索适配和结构化报告链，LangGraph 负责固定诊断节点与分支。LLM 自由工具路由关闭，所有建议继续固定 `execution_allowed=false`。

默认配置为 `configs/service_framework_rc2.yaml`：

```powershell
docker build -f deployment/Dockerfile -t aiops-fault-diagnosis-agent:framework-rc2 .
$env:AIOPS_API_BIND='127.0.0.1:38000'
$env:AIOPS_UI_BIND='127.0.0.1:38501'
docker compose --env-file .env `
  -f deployment/compose.yaml `
  -f deployment/compose.framework-rc2.yaml `
  -f deployment/compose.rc2-runtime-mounts.yaml `
  up -d --no-build
```

也可以直接运行 `deployment/switch-to-framework-rc2.ps1`。脚本会先备份 SQLite，再启动 RC2。

回退到已验证的 legacy 配置：

```powershell
docker compose --env-file .env `
  -f deployment/compose.yaml `
  -f deployment/compose.legacy-rollback-verified.yaml `
  -f deployment/compose.rc2-runtime-mounts.yaml `
  up -d --no-build
```

也可以运行 `deployment/rollback-to-legacy-rc2.ps1`。回退不迁移数据库，既有报告、revision 和待审批记录继续保留。

RC2 验收结果：

- 真实冻结索引开发集 12/12 完成、12/12 新旧流程一致、12/12 达到开发预期。
- FastAPI → SQLite → worker → 冻结索引 → LangChain → LangGraph → DeepSeek 在线链路完成 18/18，Schema 18/18，模板降级 0/18。
- 新的 30 例封存集只正式运行一次：流程 30/30、framework/legacy 一致 30/30、安全硬门禁全部为 0。
- 故障与恢复矩阵 32 项通过；全量测试 158 项通过，保留 1 个既有 pytest 配置警告。
- legacy 回退演练保留 30 份报告和 14 条待审批记录，未执行数据库迁移。

30 例封存集使用离线确定性模型验证流程，F/G/H 是隔离的 AI 角色，不等同于身份核验的自然人复核，因此这些指标不能表述为生产效果。已揭盲的旧 60 题和本轮 30 题均不可继续用于调参或下一候选正式验收。完整证据见 [Framework RC2 总验收报告](deliverables/framework_rc2_acceptance_report.md) 和 [机器可读验收清单](deliverables/results/framework_rc2_acceptance_manifest.json)。

LangGraph checkpoint 延后到 v1.2；当前 SQLite 仍是节点、预算、审批、审计和恢复的唯一权威来源。v1.2 的真实故障数据协议已冻结在 [real_incident_protocol](evaluation/v1.2/real_incident_protocol/README.md)，没有合格根因标签或时间戳时，根因准确率与 MTTD 统一为 `N/A`。

## 数据与安全边界

- 标签不参与解析、Drain3 拟合、Dmain/Ddev 抽样或在线特征。
- 模板只在训练区间拟合；验证、测试和服务仅执行冻结 `match()`。
- 原始 IP、PID、路径和消息不进入公开 API；日志查询只返回脱敏内容。
- DeepSeek Key 与 Tracking ID 只从环境或 Docker Secret 读取，不写入 Git、日志、SQLite 或报告。
- 无证据时不调用 LLM；坏 JSON、非法引用、超预算和模型故障均安全降级并留下审计记录。
- reviewer token 与哈希注册表分离，旧报告、过期、越权和幂等冲突会被阻断。
- `docs/`、`data/`、`artifacts/`、`experiments/`、`runtime/` 和本地环境全部由 Git 忽略。

## 最终成果

- [技术报告](deliverables/AIOps_v1.0_技术报告.md)
- [v1.0 验收清单](deliverables/v1_acceptance.md)
- [机器可读摘要](deliverables/results/v1_summary.json)
- [面试汇报 PPT](deliverables/AIOps故障诊断Agent_面试汇报.pptx)
- [录屏脚本](deliverables/demo/录屏脚本.md)
- [面试说明](deliverables/interview_notes.md)

完整逐例输出和本地审计报告仍保留在被忽略目录中。上述数字均来自冻结结果文件；未测内容明确标记为 N/A。
