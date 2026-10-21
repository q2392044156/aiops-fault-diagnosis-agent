# AIOps Fault Diagnosis Agent

这是一个面向 HDFS 日志与调用链数据的故障诊断研究原型。项目希望解决的不是“让大模型自动修机器”，而是一个更实际的问题：当系统出现异常时，如何把海量日志压缩成可核查的事件，再结合固定版本的运维知识，给出带证据、可追溯、可人工复核的诊断报告。

当前代码版本为 **v1.2 RC1**（Python 包版本 `1.2.0rc1`）。它已经完成代码实现、公开数据适配和本地工程验证，可作为后续接入真实故障数据与独立评测的开发基线；它仍是研究候选版本，不代表已经达到生产可用标准。

## 项目背景

传统日志告警通常只能告诉运维人员“哪里可能不正常”，不能直接回答以下问题：

- 这次异常涉及哪些日志、组件和调用链？
- 推测的原因依据是什么，能否回到原始证据核对？
- 模型失败、超预算或证据不足时，系统会不会编造结论或执行危险操作？
- 诊断中断后重试，是否会重复调用付费模型、重复生成报告或重复发起审批？
- 实验数据、参数、知识库和发布制品能否被冻结并复现？

本项目围绕这些问题逐步实现了一条受控诊断链路：先做数据清洗、会话切分和异常检测，再从版本固定的知识库中检索相关运维资料，最后由受约束的 Agent 生成带引用的报告，并把高风险或证据不足的结果交给人工复核。

系统始终遵守两个边界：

1. 只提供异常线索、证据引用和只读排查建议，不执行重启、删除、切流、写库等操作；所有建议固定为 `execution_allowed=false`。
2. 没有合格真实根因标签时，不把公开故障注入标签包装成生产根因，也不虚报根因准确率和 MTTD。

## 已完成的工作

### v1.0：从日志到受控诊断闭环

- 处理公开 HDFS 日志，形成流式解析、block 会话聚合、稳定切分和审计协议。
- 使用冻结的 Drain3 模板与 TF-IDF + Logistic Regression 完成异常检测；同时实现 LSTM 作为研究对照。
- 建立原创运维知识卡片，使用 BM25、BGE ONNX 和 RRF 做混合检索。
- 接入 DeepSeek 生成结构化诊断报告，要求报告中的结论能够引用当前发布版本中的证据。
- 实现确定性 Agent 状态机、工具预算、失败降级、人工审批和审计日志。
- 提供 FastAPI、后台 worker、Streamlit 复核台和 CPU Docker Compose 部署。

### v1.1：引入 LangChain / LangGraph，但保留确定性控制

- 增加确定性 `RetrievalQueryBuilder`，从脱敏后的组件、等级、版本和白名单信号生成最多三个检索计划。
- 使用 LangChain 适配检索器和结构化报告链，使用 LangGraph 编排固定诊断节点。
- LLM 不负责自由选择工具；工具顺序、调用预算和安全分支仍由程序控制。
- 保留原有 SQLite 业务状态、人工审批和 legacy 回退路径。
- 完成真实冻结索引对比、在线 DeepSeek 链路验证、30 例一次性封存验收和故障恢复演练。

### v1.2：补齐跨数据集、Trace、Checkpoint 和真实故障入口

- 新增公开数据适配器：
  - LogHub Hadoop 按 application 转换为脱敏日志事件。
  - HDFS v3 TraceBench 按采集场景转换为组件、操作、边和失败计数等聚合 Trace 事件。
- 将“诊断快照”和“评测标签”物理分离；服务只导入诊断快照，避免评测标签泄漏到在线诊断。
- 新增只读工具 `read_trace_summary`。服务只读取聚合 Trace 摘要，不返回原始 Trace 或公开故障标签。
- 报告 Schema 升级为 v2，支持 Trace 证据和观测结束时间；只有观测证据与知识文档证据同时存在时才进入报告生成。
- 将 LangGraph checkpoint 接入服务 SQLite，用 `<release_id>:<diagnosis_id>:<revision>` 标识一次图运行。
- 恢复时复用已经完成的工具结果，避免重复付费调用、冲突报告和重复审批。
- 定义真实故障数据协议，覆盖授权、保留期限、证据引用、五类时间戳、根因标签、导入审计和删除审计。
- 提供独立的 v1.2 Compose 配置和运行卷，并保留回退到 v1.1 Framework RC2 的配置。

## 当前系统如何工作

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
          LangGraph 固定流程 + SQLite checkpoint
                     ↓
          LangChain 结构化报告链 / 安全模板降级
                     ↓
              人工复核与审计留痕
```

三个服务的职责如下：

- `api`：接收批次、创建诊断、查询事件/报告/工具调用、处理人工审批。
- `worker`：执行异常检测、检索、Agent 工作流和报告生成。
- `ui`：提供 Streamlit 页面，供用户查看诊断结果并进行复核。

SQLite 是任务、预算、工具缓存、报告、审批和审计的业务真相源。LangGraph checkpoint 只记录流程恢复需要的图状态，不替代业务表，也不保存原始日志、评测标签或密钥。

## 实验与验证结果

### 已冻结的历史基线

| 阶段 | 结果 |
|---|---|
| 数据规模 | 11,175,629 行日志；575,061 个 block 会话；16,838 个异常会话 |
| 默认异常检测模型 | TF-IDF + Logistic Regression：测试 F1 `0.883181`、AP `0.789731`、FPR `0.006374` |
| LSTM 研究对照 | 三个 seed：测试 F1 `0.883363 ± 0.000708`、AP `0.974166 ± 0.020106` |
| 知识检索 | Hybrid Top-3：Rtest Recall `0.975`、MRR `0.9375`、nDCG `0.7827` |
| v1.0 Agent 在线评测 | 40 例 × 3 次真实 DeepSeek；任务成功、强制复核召回、引用合法率均为 `100%` |
| v1.0 工程验收 | 100 项测试通过；全新 Python 3.11.17 环境和无缓存 Compose 验收通过 |
| v1.1 Framework RC2 | 158 项测试通过；真实索引开发集 12/12；在线链路 18/18；一次性封存集 30/30；安全硬门禁均为 0 |

这些数字有明确边界：HDFS_v1 没有真实根因标签，因此异常检测指标不能解释成根因准确率；Rtest 的无答案误返回率为 20%，高于 Rdev 的 10%；v1.0 的 LLM 可选工具路由准确率仅 55%，低于 80% 门槛，所以正式流程关闭了自由工具路由。

### v1.2 RC1 验证结果

| 验证项 | 结果 |
|---|---|
| 公开数据转换 | 419/419 个事件成功；419 个诊断快照与 419 个标签一一对应 |
| 数据构成 | LogHub Hadoop 55 个日志事件；HDFS v3 TraceBench 364 个 Trace 事件 |
| 稳定分组切分 | development 265、calibration 87、public independent_test 67 |
| 服务导入 | 419 个事件成功；重复导入保持幂等 |
| 自动化测试 | 全量 `164 passed`；保留 1 个既有 pytest `cache_dir` 警告 |
| 在线工程验证 | 3/3 个真实 DeepSeek 开发案例通过；每例 1 次模型调用；Schema v2 3/3 |
| 在线调用规模 | 共 5,958 tokens，估算费用约 `¥0.012810` |
| 运行时安全门禁 | 非法引用、越权工具、可执行建议、预算突破、标签泄漏、恢复后重复调用/审批等检查均为 0 |
| 容器验证 | `aiops-fault-diagnosis-agent:v1.2-rc1` 构建通过；API、worker、UI 的 Compose 配置验证通过 |

v1.2 的三个在线案例来自开发分区，只能证明工程链路能够工作，不能证明生产诊断效果。公开 `independent_test` 是组隔离分区，但数据和标签已经公开，不是严格封存盲测。TraceBench 的故障注入标签也没有经过真实工单和独立人员确认，因此生产根因 Top-1、Top-3、MRR、误报率和 MTTD 均为 `N/A`。

详细证据见 [v1.2 RC1 实施报告](deliverables/v1.2_RC1_实施报告.md)、[v1.2 评测摘要](evaluation/v1.2/v12_rc1_validation/report.md) 和 [机器可读结果](evaluation/v1.2/v12_rc1_validation/result.json)。

## 项目结构

```text
aiops-fault-diagnosis-agent/
├─ configs/                    # 数据、模型、检索、Agent 和服务配置
├─ deployment/                 # Dockerfile、Compose、切换与回退配置
├─ evaluation/                 # 冻结评测集、v1.2 协议和可提交的验证摘要
├─ knowledge/                  # 原创运维知识卡片、来源与检索评测数据
├─ scripts/                    # 验收、评测、公开数据准备和在线验证脚本
├─ src/aiops_diag/
│  ├─ data/                    # 数据下载、解析、审计、v1.2 适配与真实故障生命周期
│  ├─ modeling/                # LR、LSTM、统一指标和冻结协议
│  ├─ retrieval/               # BM25/BGE/RRF 检索、评测与发布
│  ├─ rag/                     # DeepSeek 客户端、结构化报告和预算控制
│  ├─ agent/                   # v1.0 受控 Agent
│  ├─ agent_v11/               # v1.1 查询构建、候选流程和评测
│  ├─ framework_v12/           # LangChain/LangGraph、v1.2 Trace 与 checkpoint
│  ├─ service/                 # FastAPI、worker、SQLite、Streamlit 和发布验证
│  └─ release/                 # 发布冻结、校验和导出
├─ tests/                      # 单元、集成、恢复、安全和 v1.2 定向测试
├─ deliverables/               # 与项目实现直接相关的验收报告和机器可读清单
├─ pyproject.toml              # 包元数据与依赖声明
└─ README.md
```

`data/`、`artifacts/`、`experiments/`、`runtime/` 和本地环境目录默认不提交 Git：它们分别保存原始/处理数据、冻结制品、实验中间结果和运行时数据库。复现实验时需要在本地准备这些内容。

## 如何运行

### 1. 环境要求

- Python `3.11`（项目声明范围为 `>=3.11,<3.12`）
- Conda（推荐）
- Docker 与 Docker Compose（仅容器部署需要）
- DeepSeek API Key（仅在线报告生成需要；离线测试和模板降级不需要）

以下命令均在仓库根目录执行。

### 2. 创建开发环境

现有 `environment.yml` 包含研究依赖；v1.2 还需要安装锁定的 Framework 依赖：

```powershell
conda env create --file environment.yml
conda run --name aiops-fault-diagnosis-agent python -m pip install -r requirements-framework-lock.txt
conda run --name aiops-fault-diagnosis-agent python -m pip install -e ".[dev,research,framework]" --no-deps
conda run --name aiops-fault-diagnosis-agent python -m pip check
```

如果不需要重新创建环境，可直接在已有 Python 3.11 环境中安装 `requirements-framework-lock.txt`，再以 editable 模式安装本项目。

### 3. 运行测试

```powershell
conda run --name aiops-fault-diagnosis-agent python -m pytest -q
```

只验证 v1.2：

```powershell
conda run --name aiops-fault-diagnosis-agent python -m pytest -q `
  tests/test_v12_external_data.py tests/test_v12_runtime.py tests/test_framework_v12.py
```

### 4. 准备并审计 v1.2 公开数据

先按 `configs/data_v12_external.yaml` 中的 `source_root` 放置 LogHub Hadoop 与 HDFS v3 TraceBench 数据，再运行：

```powershell
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.data `
  v12-external prepare --config configs/data_v12_external.yaml

conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.data `
  v12-external audit --config configs/data_v12_external.yaml
```

将某个分区导入服务 SQLite：

```powershell
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.data `
  v12-external import-service `
  --config configs/data_v12_external.yaml `
  --split development `
  --database runtime/v12/service.sqlite3 `
  --artifact-root runtime/v12/imports
```

### 5. 运行 v1.2 评测

```powershell
conda run --name aiops-fault-diagnosis-agent python scripts/evaluate_v12.py `
  --database runtime/v12/service.sqlite3 `
  --output evaluation/v1.2/v12_rc1_validation
```

在线小规模验证需要在当前 shell 中设置 `DEEPSEEK_API_KEY` 和 `DEEPSEEK_TRACKING_ID`，或按 `.env.example` 准备本地 `.env`；密钥文件不会提交 Git。

```powershell
conda run --name aiops-fault-diagnosis-agent python scripts/validate_v12_online.py --count 3
```

### 6. 本地启动 API 与 worker

发布制品和数据路径由 `configs/service_v12_rc1.yaml` 指定。准备好相应的本地制品后执行：

```powershell
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.service `
  verify --config configs/service_v12_rc1.yaml

# 终端 1
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.service `
  worker --config configs/service_v12_rc1.yaml

# 终端 2
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.service `
  serve --config configs/service_v12_rc1.yaml
```

本地 API 默认监听 `http://127.0.0.1:8000`，接口文档位于 `http://127.0.0.1:8000/docs`。

### 7. 使用 Docker Compose 启动 v1.2

```powershell
docker build -f deployment/Dockerfile `
  -t aiops-fault-diagnosis-agent:v1.2-rc1 .

docker compose --env-file .env `
  -f deployment/compose.yaml `
  -f deployment/compose.v12-rc1.yaml `
  up -d --no-build
```

容器启动后：

- OpenAPI：`http://127.0.0.1:8012/docs`
- Streamlit：`http://127.0.0.1:8512`

v1.2 使用独立运行卷。需要回退时，在同一组 Compose 命令中再追加 `-f deployment/compose.v12-rollback.yaml`，即可切回 Framework RC2 镜像和独立回退卷；该过程不会迁移或覆盖 v1.2 数据库。

## 真实故障数据生命周期

真实故障记录必须符合 [冻结 Schema](evaluation/v1.2/real_incident_protocol/incident.schema.json)。常用命令如下：

```powershell
# 只校验文件，不写数据库
python -m aiops_diag.data incident validate --input incident.json

# 导入、审计与删除
python -m aiops_diag.data incident import --input incident.json --database runtime/v12/service.sqlite3
python -m aiops_diag.data incident audit --incident-id INCIDENT_ID --database runtime/v12/service.sqlite3
python -m aiops_diag.data incident delete --incident-id INCIDENT_ID `
  --database runtime/v12/service.sqlite3 --reason "保留期限已到"
```

导入前会检查授权有效性、时区、截止时间和事后信息泄漏；根因标签或时间戳不合格时，相关根因指标与 MTTD 自动返回 `N/A`。

## 安全与复现约束

- 标签不参与解析、模板拟合、开发抽样或在线特征构造。
- 模板只在训练区间拟合，验证、测试和服务阶段只使用冻结 `match()`。
- 原始 IP、PID、路径、命令、URL、密钥样式和提示注入文本会被过滤或替换。
- DeepSeek Key 和 Tracking ID 只从环境变量或 Docker Secret 读取，不写入 Git、日志、SQLite 或报告。
- 无证据时不调用 LLM；坏 JSON、非法引用、超预算和模型故障都会安全降级并留下审计记录。
- 审批只表示人工看过报告，不会触发实际运维操作。
- 镜像以非 root UID `10001` 运行，使用只读根文件系统、移除 capabilities，并启用 `no-new-privileges`。

当前版本的下一步不是继续在公开标签上调参，而是按冻结协议接入经过授权、脱敏和独立签署的真实事件，建立按时间、集群和故障族隔离的新封存集，再运行一次正式评测。
