# AIOps Fault Diagnosis Agent

[![ci](https://github.com/q2392044156/aiops-fault-diagnosis-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/q2392044156/aiops-fault-diagnosis-agent/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> 面向 HDFS 日志的故障诊断研究原型：把海量日志压缩成可核查的事件，结合冻结版运维知识，输出带证据、可追溯、可人工复核的诊断报告。

当前版本：**1.2.0rc1**。

---

## 1. 项目背景

HDFS 故障排查通常面临三个问题：

1. **日志量大**：一次故障会同时产生 NameNode、DataNode、客户端和容器日志，人工很难在短时间内定位关键证据。
2. **噪声多**：大量 INFO、重复模板、启动日志和正常 WARN 会淹没真正的故障行。
3. **结论难验证**：只用大模型生成一段根因描述，既无法确认它是否看过日志，也无法确认引用是否真实存在。

项目要解决的不是“让模型自动修机器”，而是：

> 当系统异常时，如何把原始日志变成可审计的事件，再基于证据和知识生成可复核的诊断报告。

系统坚持两条边界：

- 只输出异常线索、证据引用和只读排查建议，**不执行**重启、删除、切流、写库等动作；所有建议固定 `execution_allowed=false`。
- 没有可靠真实根因标签时，不把实验室注入标签包装成生产准确率，也不虚报 Top-1 或 MTTD。

---

## 2. 项目总体介绍

项目分成两条链路：

| 链路 | 目标 | 输入 | 输出 |
| --- | --- | --- | --- |
| 离线数据流程 | 产生可靠 event | 故障注入、正常流量、日志、指标、incident | 窗口、门禁结果、event、评测结果 |
| 在线诊断流程 | 把 event 诊断成报告 | event、证据日志、104 卡知识库 | 候选根因、证据引用、严格 JSON 报告 |

核心设计：

- 检测与诊断分离：检测只判断“有没有异常”，诊断才回答“可能是什么原因”；
- 滑动窗口统一：**60 秒 / 10 秒步长 / 每组件 / 最多 500 行**；
- 一个 PASS 窗口创建一个 event，而不是一个案例只建一个 event；
- 证据选择不是固定截断，而是按信号、严重度、模板稀有度、组件和时间评分，再做签名去重和 token 预算；
- RAG 使用 104 张 HDFS 运维卡，BM25 + BGE + RRF 混合召回；
- 诊断是固定 7 节点状态机，不是自由 Agent 循环；
- 报告必须通过 Pydantic Schema、根因码和引用白名单校验。

---

## 3. 总体目标

### 3.1 业务目标

- 从 HDFS 日志中识别卷故障、心跳丢失、NameNode 安全模式等异常；
- 把异常窗口压缩成少量 event，降低诊断成本；
- 给出带日志证据和知识证据的候选根因；
- 对证据不足、低置信度、高风险建议要求人工复核。

### 3.2 工程目标

- **可复现**：模板、检测器、知识库、评测集都冻结版本；
- **可解释**：每个节点、每次工具调用、每条证据、每个引用都可追踪；
- **可恢复**：状态和 checkpoint 落到 SQLite；
- **可评测**：检测 FPR/Recall、事件 Top-1、案例 Top-1、证据召回、引用覆盖分开统计；
- **安全**：只读工具、引用白名单、人工审批、执行开关固定关闭。

### 3.3 非目标

- 不做自动修复、自动重启、自动切流；
- 不把实验室注入结果当成生产工单准确率；
- 不追求“一个 LLM 调用解决所有问题”。

---

## 4. 代码框架

```text
src/
├─ offline/                    # 离线数据流程
│  ├─ capture/                 # 采集入口、脚本索引
│  ├─ ingestion/               # adapter、canonical、窗口、incident
│  ├─ detection/               # Drain3、LSTM、severity-first 门禁、selection
│  └─ evaluation/              # 检测/证据评测、红队、轨迹评测
├─ online/                     # 在线诊断流程
│  ├─ diagnosis/               # 7 节点引擎、evidence、tools、query_v11
│  ├─ knowledge/               # 104 卡 RAG、BM25/BGE/RRF、release
│  └─ reporting/               # 报告 Schema 入口
└─ aiops_diag/
   ├─ common.py                # 哈希、配置、序列化等共享工具
   ├─ platform/                # FastAPI、worker、SQLite、Streamlit、MCP
   ├─ release/                 # 发布清单与哈希
   └─ data/ detection/ diagnosis/ knowledge/ evaluation/
                               # 旧导入兼容 shim
```

目录职责：

| 目录 | 职责 |
| --- | --- |
| `src/offline/capture` | 故障注入、正常采集、incident 与证据落盘入口 |
| `src/offline/ingestion` | HDFS_v1 / Docker / WSL adapter、canonical、滑动窗口 |
| `src/offline/detection` | 按来源 Drain3 模板、severity-first 门禁、事件构建 |
| `src/offline/evaluation` | 离线评测、红队、轨迹与框架对照 |
| `src/online/diagnosis` | 7 节点诊断、结构化证据选择、工具调用 |
| `src/online/knowledge` | 104 卡知识库、混合检索、知识 release |
| `src/online/reporting` | 报告 Schema 入口 |
| `src/aiops_diag/platform` | API、worker、SQLite、审批、审计、MCP |
| `ops/lab` | Docker/WSL 实验台、案例采集、批量重放 |
| `ops/scripts` | 检测、事件、证据、引用评测脚本 |
| `resources` | 配置、知识卡、评测结果、冻结协议 |
| `tests` | 单元、集成、结构和回归测试 |
| `demo` | 离线端到端演示 |

业务实现已经迁入 `offline` / `online`；`src/aiops_diag` 只保留共享基础设施和旧导入兼容 shim。

---

## 5. 整体流程

### 5.1 离线数据流程

```text
故障注入 + 正常流量采集
        ↓
日志 / 指标 / incident / 证据
        ↓
多格式 adapter + canonical 规范化
        ↓
60s / 10s 滑动窗口（按组件）
        ↓
按来源 Drain3 模板
        ↓
severity-first 门禁
        ↓
每个 PASS 窗口创建一个 event
        ↓
离线评测：FPR / Recall / 事件 / 证据 / 引用
```

门禁规则：

- ERROR / FATAL：直接 PASS，除非命中显式良性错误白名单；
- WARN：只有出现新模板或频次超过正常基线时才 PASS；
- INFO：用模板新颖度兜底，阈值默认 0.10；
- 不同来源使用不同 Drain3 模板和冻结阈值。

### 5.2 在线诊断流程

```text
event
  ↓
RECEIVED
  ↓
VALIDATED
  ↓
DETECTED
  ↓
EVIDENCE_COLLECTED
  ↓
RETRIEVED
  ↓
HYPOTHESES_RANKED
  ↓
REPORT_VALIDATED
  ↓
严格 JSON 报告 + 人工复核标记
```

节点职责：

| 节点 | 工作 |
| --- | --- |
| RECEIVED | 接收 event，初始化预算、trace 和状态 |
| VALIDATED | 校验事件、诊断任务、预算和状态 |
| DETECTED | 读取异常分数、窗口、组件等元信息 |
| EVIDENCE_COLLECTED | 查询窗口日志，做结构化证据选择 |
| RETRIEVED | 拼查询，执行 104 卡 RAG，合并日志/文档证据 |
| HYPOTHESES_RANKED | 按信号、先验和证据排序候选根因 |
| REPORT_VALIDATED | Schema、引用、根因码、动作安全校验，保存报告 |

固定预算：

```text
8 次工具调用 / 3 次 LLM 调用 / 12k token / 120 秒 / 最多 2 次修订
```

### 5.3 证据选择

`EvidenceSelector` 的处理过程：

1. 统计组件，选择 `focus_component`；
2. 逐行计算信号、严重度、模板稀有度、时间近因、组件权重；
3. 堆栈行折叠，重复消息按签名去重；
4. 按“信号/弱信号 → ERROR/WARN → 窗口尾部 → 其余高分”排序；
5. 应用 **50 行上限 + 2000 token 预算**；
6. 输出结构化质量：组件、级别、模板多样性、时间范围、token、是否充分。

### 5.4 RAG 与报告

```text
证据 + 组件 + 根因码
        ↓
BM25 + BGE-small-zh ONNX + RRF
        ↓
根因码卡注入 + doc 级去重
        ↓
文档证据 + 引用白名单
        ↓
报告生成与严格 JSON 校验
```

报告必须包含：

- `summary`
- `observed_facts`
- `hypotheses`（最多 5 个）
- `checks`（只读）
- `missing_information`
- `limitations`

所有 `support_ids` / `counter_ids` / `citation_ids` 必须来自当前证据白名单。

---

## 6. 结果展示

### 6.1 v2 数据集

v2 由三部分组成：

- Docker 有效案例：60
- WSL 原始案例：68
- WSL 卷故障补采：21
- 合计：149

Docker 原始 81 例中有 21 例卷故障注入没有产生信号，属于 invalid injection，已隔离；用 WSL 卷故障重新补采 21 例替代。

### 6.2 诊断结果

| 数据 | 案例 | 事件 | 事件 Top-1 | 案例 Top-1 |
| --- | --- | --- | --- | --- |
| Docker 有效 | 60 | 232 | 218/232 = 94.0% | 60/60 |
| WSL 原始 | 68 | 196 | 189/196 = 96.4% | 67/68 |
| WSL 补采 | 21 | 38 | 38/38 = 100% | 21/21 |
| **合计** | **149** | **466** | **445/466 = 95.5%** | **148/149 = 99.33%** |

### 6.2.1 故障族与网络分区

当前 v2 覆盖 3 个故障族：

| 根因码 | 故障 | v2 样本 |
| --- | --- | --- |
| `DN_VOLUME` | 卷满/卷失败 | 66 |
| `DN_HEARTBEAT` | DataNode 心跳丢失 | 37 |
| `NN_SAFE_MODE` | NameNode 安全模式 | 46 |

新增 **网络分区** 实验族，根因码使用受控枚举 `NETWORK_CONNECTIVITY`：

- 注入：断开 DataNode 的 Docker 网络，并重启 DataNode，迫使它重新连接 NameNode；
- 恢复：重新连接网络，启动 DataNode，等待 3 个 DataNode 恢复；
- 关键证据：`Retrying connect`、`Connection timed out`、`No route to host`；
- 有效性：必须观测到 `Retrying connect` 等信号，否则样本判 invalid。

首例完整链路：

```text
1 个案例 / 19 个事件
门禁 PASS
事件 Top-1 = 1.0
候选根因 = NETWORK_CONNECTIVITY
```

这说明“注入 → 采集 → adapter → 门禁 → event → 证据 → RAG → 7 节点 → 报告”已经打通；当前样本量仍是 1，后续按计划补到 20–30 例，暂不计入 v2 149 例主表。

运行：

```powershell
python ops/lab/harness/run_case.py --fault NETWORK_PARTITION --observe 30 --case-root ops/lab/network_cases --require-signal
```

### 6.3 检测结果

| 指标 | Docker | WSL |
| --- | --- | --- |
| 正常窗口 FPR | 0/166 | 0/74 |
| 正常窗口数 | 553 | 244 |
| 窗口 Recall | 275/294 | 212/212 |
| 案例 Recall | 80/81 | 68/68 |

### 6.4 证据与引用

| 指标 | Docker | WSL |
| --- | --- | --- |
| 50 行证据召回 | 0.698 | 1.000 |
| 50 行证据精度 | 0.145 | 0.128 |
| 证据充分率 | 60/81 | 67/68 |

检测和证据表按原始有效实验统计；v2 诊断表剔除了 21 例 Docker invalid injection，因此 Docker 案例数从 81 变为 60。

v2 引用覆盖：

```text
583/667 = 87.4%
```

### 6.5 检测基线

HDFS_v1 公开数据上的冻结检测基线：

| 指标 | 值 |
| --- | --- |
| F1 | 0.883181 |
| AP | 0.789731 |
| FPR | 0.006374 |

### 6.6 结果解读

- **事件级 95.5% 是更可信的主指标**：每个 PASS 窗口独立诊断；
- **案例级 99.33% 是 Any-Event 口径**：同一案例只要有一个事件命中就算案例命中，会高于事件级；
- **Docker 证据召回 0.698 是当前短板**：瓶颈主要是日志里缺少证据，不是选择算法；
- **引用覆盖 87.4%**：报告只引用部分支撑证据，不等于所有 gold 行都被引用。

---

## 7. 失败案例与根因分析

### 7.1 失败分类

| 类型 | 数量/表现 | 根因 | 当前处理 |
| --- | --- | --- | --- |
| Docker 卷注入无效 | 21 例 | Docker loop 卷没有产生 ENOSPC/volume failed | 隔离，不计入 v2；用 WSL 重采替代 |
| 事件级错误 | 21 个事件 | 窗口噪声、证据不足、候选排序波动 | 案例级可被其他窗口救回 |
| 案例级错误 | 1 例 | 证据或排序不足 | 保留为失败样例 |
| 引用未覆盖 gold | 84 行 | 报告只引用少量支撑证据 | 引用覆盖作为独立指标 |
| LangGraph parity | 1/38 事件 | 续行窗口缺少可信组件，已加根因码 fallback | 21/21 案例对齐 |

### 7.2 根因一：Docker 卷注入无效

表现：

- 重放后日志没有 `No space left on device`；
- 也没有 `failed volume`；
- 采集窗口和容器日志都存在，但注入本身没有制造故障。

处理：

- 增加 `--require-signal`，没有信号直接判 invalid；
- 21 例标记为 invalid injection，不进入 v2；
- 用 WSL 卷故障重放 21 例，证据充分率 100%。

这不是模型失败，而是**数据采集失败**。如果不隔离，会把“没有故障”误算成“模型没诊断出来”。

### 7.3 根因二：事件级低于案例级

事件级 95.5%，案例级 99.33%，差距来自：

- 一个案例被切成多个滑动窗口；
- 有些窗口只有上下文，没有直接证据；
- 有些窗口证据正确但候选排序错误；
- 同一案例的其他窗口可能命中，所以案例级被“救回”。

这说明：

> 事件级错误不一定代表案例诊断失败，但会直接影响单窗口诊断体验，后续需要合并相邻事件或做事件级投票。

### 7.4 根因三：Docker 证据召回偏低

Docker 50 行证据召回 0.698，主要因为：

- 卷故障的 gold 包含大量启动期 volume/disk/storage 行；
- 证据选择优先保留信号行和窗口尾部，启动期行容易被去重；
- 部分案例日志中确实没有直接 ENOSPC 行。

处理方向：

- 不是继续加大 50 行，而是补采 NN/DN 日志；
- 对证据不足案例单独标记，不把“缺证据”混入“算法错误”。

### 7.5 根因四：引用覆盖不足

引用覆盖 87.4%，缺失的 12.6% 主要是：

- gold 标注了启动期卷相关行；
- 报告只引用最终支撑候选的少量证据；
- 文档证据和日志证据的引用粒度不同。

引用覆盖低不等于报告错误，但说明“报告引用”与“证据 gold”不是同一口径，需要分开解释。

### 7.6 根因五：LangGraph parity 回归

修复前，部分窗口只剩续行、可信组件为空，query builder 没有生成检索计划，LangGraph 最终没有文档证据，21 例里只有 15 例案例命中。

修复方式：query builder 没有计划时，用根因码构造安全 fallback 检索计划，仍然只使用白名单组件和允许的查询词。

| 后端 | 事件 Top-1 | 案例 Top-1 |
| --- | --- | --- |
| Native | 38/38 = 100% | 21/21 = 100% |
| LangGraph | 37/38 = 97.4% | 21/21 = 100% |

当前结论：

> 21 例补采批次上，LangGraph 案例级已经与 Native 对齐；事件级还差 1 个，全量 v2 尚未重跑，因此仍不能宣称双后端完全等价。

### 7.7 失败样例怎么用

不建议只展示成功案例。面试或评审时建议讲一个失败案例：

1. 这个 event 为什么没有命中；
2. 是证据缺失、检索缺失还是排序错误；
3. 案例级是否被其他事件救回；
4. 下一步是补数据、改证据选择，还是改排序。

---

## 8. 环境搭建

### 8.1 基础要求

| 依赖 | 要求 |
| --- | --- |
| Python | 3.11（`>=3.11,<3.12`） |
| Conda | 推荐 |
| Docker | 仅 Docker 实验需要 |
| WSL2 + Ubuntu | 仅 WSL 实验需要 |
| JDK 11 + Hadoop 3.3.6 | 仅 WSL 实验需要 |

### 8.2 安装

```powershell
conda env create --file environment.yml
conda run --name aiops-fault-diagnosis-agent python -m pip install -r requirements-framework-lock.txt
conda run --name aiops-fault-diagnosis-agent python -m pip install -e ".[dev,framework]" --no-deps
conda run --name aiops-fault-diagnosis-agent python -m pip check
```

需要重建 ONNX/BGE 制品时再加 `research`：

```powershell
conda run --name aiops-fault-diagnosis-agent python -m pip install -e ".[dev,framework,research]" --no-deps
```

### 8.3 环境变量

复制示例文件：

```powershell
Copy-Item .env.example .env
```

在线 LLM 需要：

```text
DEEPSEEK_API_KEY=...
```

离线 Demo、检测、证据选择和模板报告不需要 API Key。

---

## 9. 配置说明

| 配置 | 作用 |
| --- | --- |
| `resources/configs/agent.yaml` | 7 节点预算、只读工具、报告和审批策略 |
| `resources/configs/rag.yaml` | BM25/BGE 权重、Top-K、RRF 参数 |
| `resources/configs/service_v12_rc1.yaml` | API/worker/UI 服务配置 |
| `resources/configs/release.yaml` | 发布和冻结配置 |
| `resources/knowledge/` | 104 卡知识库和 chunk 元数据 |
| `resources/evaluation/` | 冻结评测协议与结果 |
| `artifacts/` | 检测器、模板、RAG release（本地生成，不提交） |
| `.env` | 本地密钥（已忽略） |

关键配置原则：

- 检测器、模板、知识库必须使用冻结 release；
- 评测集和阈值冻结后不再调参；
- `execution_allowed` 固定为 `false`；
- 高风险动作必须人工审批。

---

## 10. 快速开始

### 10.1 离线 Demo（无需 API Key）

```powershell
conda run --name aiops-fault-diagnosis-agent python demo/run_demo.py
```

机器可读模式：

```powershell
conda run --name aiops-fault-diagnosis-agent python demo/run_demo.py --json
```

预期输出：

- `diagnosis_status`
- `final_status=APPROVED_REPORT`
- 工具调用次数
- 证据数量
- 报告引用

### 10.2 在线模式（需要 Key）

```powershell
conda run --name aiops-fault-diagnosis-agent python demo/run_demo.py --online
```

### 10.3 测试与结构校验

```powershell
conda run --name aiops-fault-diagnosis-agent python -m pytest -q --basetemp=.pytest-tmp
conda run --name aiops-fault-diagnosis-agent python ops/scripts/validate_project_structure.py
```

---

## 11. 完整流程

### 11.1 WSL 单机实验

```bash
bash ops/lab/wsl/reset_volume.sh
python ops/lab/wsl/run_case.py --fault DN_VOLUME --database runtime/lab/wsl.sqlite3 --require-signal
python ops/lab/wsl/run_case.py --fault DN_HEARTBEAT --database runtime/lab/wsl.sqlite3 --require-signal
python ops/lab/wsl/run_case.py --fault NN_SAFE_MODE --database runtime/lab/wsl.sqlite3 --require-signal
```

说明见 `ops/lab/wsl/README.md`。

### 11.2 Docker Compose 批量实验

```powershell
docker compose -f ops/lab/compose.yaml up -d
python ops/lab/harness/run_batch.py --real --per-fault 7 --observe 12 --database runtime/lab/real_batch.sqlite3 --require-signal
docker compose -f ops/lab/compose.yaml down -v
```

### 11.3 门禁与 event 重放

```powershell
python ops/lab/harness/run_gate_batch.py \
  --cases ops/lab/wsl_cases \
  --database runtime/lab/events_wsl.sqlite3 \
  --source-db runtime/lab/wsl.sqlite3 \
  --source-type wsl \
  --detector artifacts/detectors/wsl_sliding_v4.json \
  --detector-release novelty_wsl_sliding_v4 \
  --template-dir artifacts/templates/wsl \
  --gate-output resources/evaluation/lab/gate_wsl.json \
  --window-seconds 60 --window-step 10 --max-rows 500
```

### 11.4 评测

检测：

```powershell
python ops/scripts/evaluate_windows.py --cases ops/lab/wsl_cases --source-type wsl --normal-dir ops/lab/normal --output resources/evaluation/lab/windows_wsl.json
```

事件与案例：

```powershell
python ops/scripts/evaluate_events.py \
  --gates resources/evaluation/lab/gate_wsl.json \
  --database runtime/lab/events_wsl.sqlite3 \
  --cases ops/lab/wsl_cases \
  --output resources/evaluation/lab/events_wsl.json
```

证据：

```powershell
python ops/scripts/evaluate_evidence.py \
  --cases ops/lab/wsl_cases \
  --source-type wsl \
  --output resources/evaluation/lab/evidence_wsl.json
```

引用：

```powershell
python ops/scripts/evaluate_citations.py \
  --gates resources/evaluation/lab/gate_wsl.json \
  --database runtime/lab/events_wsl.sqlite3 \
  --cases ops/lab/wsl_cases \
  --output resources/evaluation/lab/citations_wsl.json
```

### 11.5 v2 合并与冻结切分

```powershell
python ops/scripts/merge_evaluations.py   --docker resources/evaluation/lab/p2_events_docker_valid_eval.json   --wsl resources/evaluation/lab/p1_events_wsl_eval.json   --recaptured resources/evaluation/lab/recaptured_final_eval.json   --docker-citations resources/evaluation/lab/p2_citations_docker_valid.json   --wsl-citations resources/evaluation/lab/p1_citations_wsl.json   --recaptured-citations resources/evaluation/lab/recaptured_final_citations.json   --output resources/evaluation/lab/merged_v2.json

python ops/scripts/freeze_v2_split.py   --output resources/evaluation/lab/v2_split.json   --manifest resources/evaluation/lab/recaptured_manifest.json   --docker ops/lab/real_batch_cases   --wsl ops/lab/wsl_cases   --recaptured ops/lab/recaptured_cases/wsl_volume
```

### 11.6 数据与制品

以下目录不提交 Git，需在本地生成：

- `data/`
- `artifacts/`
- `experiments/`
- `runtime/`
- `ops/lab/*_cases/`

---

## 12. 边界与限制

1. **不是生产准确率**  
   149 例是实验室注入数据，不是生产工单；不能把 99.33% 当成线上准确率。

2. **故障族仍然有限**  
   只覆盖卷、心跳、安全模式；没有网络分区、磁盘 IO、HA、block 损坏和多故障叠加。

3. **Docker 21 例被隔离**  
   不是模型失败，是注入无效；v2 用 WSL 补采替代。

4. **事件级仍低于案例级**  
   事件级 95.5%，案例级 99.33%；单窗口诊断仍有波动。

5. **证据层有短板**  
   Docker 50 行证据召回 0.698，证据充分率 60/81；部分案例日志里没有直接证据。

6. **引用覆盖不是 100%**  
   87.4% 是按行级 gold 统计；报告只引用少量支撑证据，和 gold 口径不完全一致。

7. **LangGraph 接近对齐但未完全等价**  
   21 例批次上 Native 38/38，LangGraph 37/38；案例级 21/21 已对齐，事件级还差 1 个，全量 v2 未重跑。

8. **MTTD 不可用**  
   部分实验日志含观测窗，部分没有可靠人工确认时间，不能虚报 MTTD。

9. **只读建议**  
   所有建议 `execution_allowed=false`，不自动执行任何修复动作。

10. **评测切分不是独立盲测**  
    v2 已冻结 train/test，但仍来自同一实验体系，不能替代真实生产盲测。

---

## 13. 版本说明

当前版本为 **1.2.0rc1**。历史版本通过 Git tags / Releases 查看，本 README 不再重复维护历史版本说明。

---

## 14. License

MIT，见 [LICENSE](LICENSE)。
