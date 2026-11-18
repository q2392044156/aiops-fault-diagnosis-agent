# AIOps Fault Diagnosis Agent

[![ci](https://github.com/q2392044156/aiops-fault-diagnosis-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/q2392044156/aiops-fault-diagnosis-agent/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

面向 HDFS 日志的可解释故障诊断 Agent。覆盖离线阶段的故障采集、日志处理、异常筛选，以及在线阶段的证据选择、知识检索、根因诊断和 JSON 报告生成。

当前覆盖 4 类故障：

- 卷故障 DN_VOLUME
- 心跳丢失 DN_HEARTBEAT
- NameNode 安全模式 NN_SAFE_MODE
- 网络分区 NETWORK_CONNECTIVITY

系统只输出异常线索、证据引用和只读排查建议，不执行重启、删除、切流、写库等动作。

---

## 项目结构

    aiops-fault-diagnosis-agent/
    ├─ src/
    │  ├─ offline/                 # 离线数据流程
    │  │  ├─ ingestion/            # 解析适配、canonical、窗口、审计、下载
    │  │  ├─ case/                 # 事件契约、导入校验、受控实验记录
    │  │  └─ detection/            # 模板挖掘与特征、severity 门禁、LR/LSTM 检测器、选择实验
    │  ├─ online/                  # 在线诊断流程
    │  │  ├─ diagnosis/            # 诊断代理（Agent / CandidateAgent）、证据与信号、工具路由、检索式查询；framework/ 为 LangGraph 实现
    │  │  └─ knowledge/            # 语料与混合检索、发布与门禁、报告生成（generation/）
    │  ├─ evaluation/              # 跨离线/在线的评测层
    │  │  ├─ agent/                # 预算、报告案例、错误分类、轨迹评测编排（能跑真实 Agent）
    │  │  ├─ retrieval/            # 检索协议、候选池、人工复核、冻结、盲测、runbook 复核
    │  │  └─ *.py                  # comparison 框架对照、redteam 红队、router 路由评测、trajectory 轨迹落盘
    │  └─ aiops_diag/              # 共享基础设施
    │     ├─ common.py             # 哈希、配置解析、清单校验、分位数
    │     ├─ constants.py          # 工具白名单与预算裁剪顺序
    │     ├─ nodes.py              # 诊断节点固定顺序
    │     ├─ platform/             # API、worker、SQLite、UI、MCP、incident 命令、发布校验
    │     └─ release/
    ├─ ops/
    │  ├─ lab/                     # Docker/WSL 实验台、采集、批量重放
    │  ├─ scripts/                 # 门禁、事件、证据、引用、评测脚本
    │  ├─ deployment/              # 健康检查与部署辅助
    │  └─ redteam/                 # 红队语料
    ├─ resources/
    │  ├─ configs/                 # Agent、RAG、检测、服务与发布配置
    │  ├─ knowledge/               # 知识卡和知识库
    │  ├─ evaluation/              # 冻结协议、切分与评测结果
    │  └─ releases/                # 检测器 release 目录（novelty_*，各含 registry.json）
    ├─ tests/                      # 自动化测试（256 个用例）
    ├─ documentation/              # 架构、实验报告与验收记录
    ├─ demo/                       # 离线端到端演示
    ├─ data/                       # 原始与处理后的日志数据（本地）
    ├─ experiments/                # 评测与调参产物（本地）
    ├─ artifacts/                  # 检测器/RAG/发布清单（本地生成）
     └─ runtime/                    # SQLite、临时运行数据（本地生成）

目录约定的细节见 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)；发布清单的校验方式与行尾要求见
[documentation/发布校验策略.md](documentation/发布校验策略.md)。

---

## 工作流程

### 离线阶段

    故障注入 / 正常流量采集
            ↓
    日志 + 指标 + incident
            ↓
    多格式 adapter + canonical 规范化
            ↓
    60s / 10s 滑动窗口（按组件）
            ↓
    按来源 Drain3 模板
            ↓
    severity-first 门禁
            ↓
    PASS 窗口事件化（相接窗口合并）

门禁规则：

- ERROR/FATAL 优先 PASS；
- WARN 只有新模板或频次超过正常基线才 PASS；
- INFO 用 novelty 兜底；
- 不同来源使用不同模板和冻结阈值。

同一案例、同一组件、时间重叠或相接的 PASS 窗口合并为一个 event，避免同一段故障重复诊断。

### 在线阶段

    event
      ↓
    RECEIVED → VALIDATED → DETECTED
      ↓
    EVIDENCE_COLLECTED
      ↓
    RETRIEVED
      ↓
    HYPOTHESES_RANKED
      ↓
    REPORT_VALIDATED
      ↓
    带引用的 JSON 报告

核心处理：

- 证据选择：组件关注、可解释信号本体（正则 + 权重 + direct/context/support）、严重度/稀有度/时间评分、堆栈与重复消息去重、50 行 + 2000 token 预算；
- RAG：104 卡、154 chunk，BM25 + BGE ONNX + RRF，根因码卡注入；
- 报告：Pydantic Schema、根因码白名单、引用白名单、只读动作校验。

预算：

    8 次工具调用 / 3 次 LLM 调用 / 12k token / 120 秒 / 最多 2 次修订

---

## 检测结果

### 统一 4 类评测

清洗后数据 132 例：

| 故障族 | 案例 |
| --- | --- |
| 卷故障 | 28 |
| 心跳丢失 | 37 |
| 安全模式 | 46 |
| 网络分区 | 21 |

切分：每类 15 例 test，共 60 例；train 72 例。

| 集合 | 案例 | 事件 | 案例多数投票 | 案例首事件 | 案例所有事件都对 | 事件 Top-1（micro） | Macro Event（macro） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| test | 60 | 143 | 60/60 = 100% | 60/60 = 100% | 60/60 = 100% | 143/143 = 100% | 1.0000 |
| train | 72 | 156 | 71/72 = 98.61% | 71/72 = 98.61% | 71/72 = 98.61% | 155/156 = 99.36% | 0.9949 |

事件级 4 类的 Macro / Micro。`事件 Top-1` 就是 Micro 的命中口径（命中数 / 事件数），下表把它拆成精确率、召回率与 F1，并给出 4 类等权的 Macro：

| 集合 | 口径 | 精确率 | 召回率 | F1 | 命中 / 事件 |
| --- | --- | --- | --- | --- | --- |
| test | Macro（4 类算术平均） | 1.0000 | 1.0000 | 1.0000 | 143/143 |
| test | Micro（全部事件汇总） | 1.0000 | 1.0000 | 1.0000 | 143/143 |
| train | Macro（4 类算术平均） | 1.0000 | 0.9949 | 0.9974 | 155/156 |
| train | Micro（全部事件汇总） | 1.0000 | 0.9936 | 0.9968 | 155/156 |

Macro 对 4 类等权，小类错一个事件就掉 1/4；Micro 按事件汇总，大类主导。train 唯一的错误事件是心跳丢失事件没有候选（`pred=null`），只产生 1 个 FN、没有 FP，所以精确率仍是 1.0000，召回率掉到 0.9936。

事件数是合并后的数量：同一案例、同一组件、时间重叠或相接的 PASS 窗口会合并为一个事件，避免同一段故障被重复诊断。改进前的逐窗口结果为 test 429、train 303 个事件（存档在 `resources/evaluation/unified4_nomerge/results.json`），合并后为 test 143、train 156；门禁和窗口召回不受影响。

“案例所有事件都对”等价于最差事件口径；多数投票和首事件会掩盖案例内单个错误事件。

事件级每类：

| 集合 | 故障族 | 案例 | 事件 | 事件 TP / FP / FN | 精确率 | 召回率 | F1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| test | 卷故障 | 15 | 31 | 31 / 0 / 0 | 1.0000 | 1.0000 | 1.0000 |
| test | 心跳丢失 | 15 | 37 | 37 / 0 / 0 | 1.0000 | 1.0000 | 1.0000 |
| test | 安全模式 | 15 | 30 | 30 / 0 / 0 | 1.0000 | 1.0000 | 1.0000 |
| test | 网络分区 | 15 | 45 | 45 / 0 / 0 | 1.0000 | 1.0000 | 1.0000 |
| train | 卷故障 | 13 | 27 | 27 / 0 / 0 | 1.0000 | 1.0000 | 1.0000 |
| train | 心跳丢失 | 22 | 49 | 48 / 0 / 1 | 1.0000 | 0.9796 | 0.9897 |
| train | 安全模式 | 31 | 62 | 62 / 0 / 0 | 1.0000 | 1.0000 | 1.0000 |
| train | 网络分区 | 6 | 18 | 18 / 0 / 0 | 1.0000 | 1.0000 | 1.0000 |

test 的混淆矩阵四类全部落在对角线上（每类 15 例全部判对），案例级误判 0；train 的心跳族有 1 例判为空（`DN_HEARTBEAT → null`），其余三类各自全对。

置信区间与报告路径：

- 案例多数投票 95% Wilson CI [0.9398, 1.0]；60/60 时非参数 cluster bootstrap 会退化为 [1.0, 1.0]，因此同时保留 Wilson 作参考；
- 事件级 Micro 的 Wilson CI：test [0.9738, 1.0]、train [0.9646, 0.9989]；cluster CI：test [1.0, 1.0]、train [0.9799, 1.0]；
- Macro Event 的 cluster CI：test [1.0, 1.0]、train [0.9826, 1.0]；100% 指标在非参数 bootstrap 下会退化为边界，不能理解为“零风险”；
- test 143 个、train 156 个事件全部报告为 `DEGRADED_TEMPLATE`，当前指标主要反映规则/模板链路，不代表 LLM 生成质量；
- test 无错误事件；train 仅 1 个心跳事件无候选（判为空，计 1 个 FN），明细见 `resources/evaluation/unified4/results.json` 的 `train.error_events`。

### 分布偏移回归集（challenge20）

统一测试集的高指标来自封闭的 4 类实验室分布。为了观察“换格式、换时间、换主机名、换故障表述”后的退化，另构造了 20 个未参与 unified4 的派生案例：

- 卷故障 7、心跳丢失 7、安全模式 6；没有网络分区；
- 四组各 5 例：跨格式/时间、删正常行、同义改写、同义改写叠加另一类故障干扰；
- 全部重渲染为 WSL 文本，时间平移 -30 天，主机名改为生产风格，标签沿用原始 incident。

| 口径 | 结果 |
| --- | --- |
| 门禁 | 20/20 PASS |
| 案例多数投票 / 首事件 / 所有事件都对 | 20/20 = 100% |
| 事件 Top-1 | 21/21 = 100% |
| 报告模式 | 21/21 DEGRADED_TEMPLATE |

分组结果：跨格式/时间 5/5、删正常行 5/5、同义改写 5/5、同义改写+干扰 5/5（事件 6/6）；卷故障 7/7、心跳 7/7、安全模式 6/6。

这组结果来自本轮改进：可解释信号本体覆盖“missed its liveness deadline”“ENOSPC”“Startup guard”等同义表述，按 strongest signal 排序替代固定根因置顶，并把相接窗口合并为一个事件（57→21）。**但这 20 例已经参与本轮规则迭代，不再是盲测 holdout；20/20 只能说明回归通过，不能证明跨分布泛化提升。** 要验证泛化，需要重新构造未参与调参的案例。

完整说明、复现命令和逐案例结果见 [resources/evaluation/challenge20/README.md](resources/evaluation/challenge20/README.md)。

### 检测门禁与窗口召回

60s / 10s 滑窗；故障窗口指结束时间晚于 fault_start 的窗口，正常集为独立采集。

| 指标 | Docker | WSL | 合计 |
| --- | --- | --- | --- |
| 正常窗口（训练 / 测试） | 553（387 / 166） | 244（170 / 74） | 797（557 / 240） |
| 正常测试窗口误报 | 0 / 166 | 0 / 74 | 0 / 240 |
| 故障窗口 Recall | 607 / 613 = 99.02% | 98 / 98 = 100% | 705 / 711 = 99.16% |
| 案例 Recall | 81 / 81 | 51 / 51 | 132 / 132 |

四行数字来自不同层的产物，别混用：

- 132 例 = Docker 81 + WSL 51，逐案例门禁记录在 `resources/evaluation/unified4/docker_gates.json`、`wsl_gates.json`（可逐例核对 PASS 与报告 ID）；
- 前三行（正常窗口、误报、故障窗口 Recall）由 `ops/scripts/evaluate_windows.py` 在窗口层算出，结果落在未提交的 `runtime/unified4/windows_docker.json`、`windows_wsl.json`（`runtime/` 已被 `.gitignore` 忽略，Git 内没有汇总文件）；
- `resources/evaluation/lab/windows_sliding_{docker,wsl}.json` 是更早的 81 / 68 例批次：正常集相同（553、244），但故障窗口是 294 / 275 与 212，不能拿来对 613 / 98；
- `607 / 613` 与逐窗口事件 `634` 不是同一分母：613 是结束时间晚于 `fault_start` 的故障窗口，607 是其中 PASS；634 是全部 PASS 事件，其中 27 个窗口在 `fault_start` 之前结束（全部来自网络分区案例，13 例各 2 个、1 例 1 个），另有 6 个故障窗口被门禁拒绝、不生成事件；`634 = 607 + 27`，`613 = 607 + 6`。WSL 的 98 个窗口全部在 `fault_start` 之后，且 98/98 PASS。

### 说明

- 主指标看 4 类事件级的 Macro / Micro（精确率、召回率、F1）与每类事件级，同时报告案例多数投票、首事件、所有事件都对、任一事件四种口径；
- 置信区间按故障族分层、以案例为重采样单元做 cluster bootstrap；100% 指标在非参数 bootstrap 下会退化为边界，同时保留 Wilson；
- 网络分区是独立批次，已并入 4 类统一切分；
- 磁盘 IO 实验因与卷故障日志不可区分，未纳入 4 类指标；
- 旧 v2 的 149 例、466 事件是历史口径，不再作为当前统一结果。

---

## 环境与配置

### 两种复现口径

| 口径 | 额外需要 | 能到什么程度 |
| --- | --- | --- |
| **A 最简**（先跑这个） | Python 3.11 + 能装 pip 包 | 248 个用例通过、8 个依赖本地发布制品的用例跳过；离线 demo、结构校验、静态检查全部可用 |
| **B 完整** | 再加 torch（CUDA 可选） | 检测器 / LSTM 训练、BGE ONNX 重建、服务发布链路 |

### A 最简：三条命令装上

    python -m pip install -r requirements-framework-lock.txt "pytest>=8,<10"
    python -m pip install -e . --no-deps
    python -m pip check

装完就是三条验证命令，不需要 API Key、不需要 GPU、不写数据库：

    python -m pytest -q                                # 新克隆 248 passed, 8 skipped；有本地 artifacts 时 256 passed
    python demo/run_demo.py --json                     # 离线端到端，约 2 秒
    python ops/scripts/validate_project_structure.py   # PASS

pwsh 7 / bash 想一行跑完前三条验证：

    python -m pytest -q && python ops/scripts/validate_project_structure.py && python demo/run_demo.py --json

日常只需要这三条验证命令；`pip check` 装完过一遍就行（若只报 `pipx` 自身的 filelock/packaging
版本冲突，那是 conda 环境自带的工具，与项目依赖无关）。

### B 完整：一条命令建 conda 环境

    conda env create --file environment.yml
    conda activate aiops-fault-diagnosis-agent

`environment.yml` 里已经带 `-e .[dev,research]`（torch 2.14.1+cu130、transformers），不用再手动装；
CPU-only 机器把 `--extra-index-url` 的 `cu130` 换成 `cpu` 即可。

### 环境要求

| 依赖 | 要求 |
| --- | --- |
| Python | 3.11（见 `.python-version`） |
| Conda | 只有 B 口径需要 |
| torch | 只有训练 / ONNX 制品需要 |
| Docker | Docker 实验需要 |
| WSL2 + Ubuntu + JDK 11 + Hadoop 3.3.6 | WSL 实验需要 |

### 配置

| 配置 | 作用 |
| --- | --- |
| .env | DeepSeek API Key，离线运行不需要 |
| resources/configs/agent.yaml | 7 节点预算、工具、审批 |
| resources/configs/rag.yaml | RAG Top-K、RRF、BGE |
| resources/configs/query_builder_v1.yaml | 检索式构造（v1.1 候选） |
| resources/configs/service.yaml | 默认服务装配：不带 `agent_backend`，走 Native 7 节点 |
| resources/configs/service_v11_candidate.yaml | v1.1 候选（Native + 检索式查询 + 门禁阈值） |
| resources/configs/service_v12_rc1.yaml | 框架候选 + checkpoint（v1.2 候选：LangGraph + LangChain 报告） |
| resources/configs/service_framework_rc2.yaml | 框架候选（LangGraph）的服务装配 |
| resources/knowledge/ | 知识卡与知识库 |
| artifacts/ | 检测器、模板、RAG release |
| runtime/ | SQLite 与运行产物 |

artifacts/、runtime/、data/、experiments/ 和 ops/lab/*_cases/ 不提交 Git。

### 三个常见问题

1. **克隆后 4 条 `test_retrieval*` 报 `Sealed development queries changed`**：密封协议的摘要是按字节算的，
   仓库里存的是 LF；Windows 上 `core.autocrlf=true` 会把工作区改成 CRLF，摘要就对不上。`.gitattributes`
   已经固定 LF，真遇到就 `git config --global core.autocrlf false` 后重新 `git checkout -- resources`。
2. **有 8 条用例 skipped**：它们要 `artifacts/releases/v1.0_service` 这类本地发布制品，而 `artifacts/`、
   `experiments/`、`data/` 都不进仓库（`publish` 还依赖 `experiments/time_event_v1/model_selection_v1/final/manifest.json`
   等上游产物）。新克隆跑不了这几条是设计如此，不是装错了。
3. **Windows 上敲 `python` 弹出应用商店**：那是 `WindowsApps` 下的占位符，不是真解释器。用
   `py -3.11`、`conda activate` 之后的 `python`，或直接写解释器绝对路径。

---

## 快速运行

### 离线 Demo（无需 API Key）

    python demo/run_demo.py
    python demo/run_demo.py --json     # 机器可读

预期输出（本机实测，约 2 秒）：

    diagnosis_status  = DEGRADED_TEMPLATE      # 模板链路出的结论，不是 LLM
    requires_review   = true                   # review_reasons = [low_confidence]
    final_status      = APPROVED_REPORT
    tool_calls        = 7
    evidence          = 7
    illegal_citations = 0
    executable_advice = 0

### 在线 Demo（需要 Key）

    cp .env.example .env      # 填 DEEPSEEK_API_KEY
    python demo/run_demo.py --online

### 静态检查

规则与标注范围都在 `pyproject.toml`；这两个工具不在最小复现口径里，先装一次：

    python -m pip install "ruff==0.17.5" "mypy==2.4.1"

之后两条命令各自独立：

    python -m ruff check .
    python -m mypy

结构校验是另一套规则，与上面的静态检查互不替代：模块目录登记、每个 `.py` 都在 README 里列出、
模块 docstring 为中文、禁止 `# 方法说明：` 一类机械注释标签、mypy 边界清单内的函数必须写返回标注。

### 可选：Makefile 快捷方式

装了 make 的环境（WSL / Git Bash / macOS / Linux）可以用等价快捷键，Windows 原生 PowerShell 直接用上面的 python 命令：

    make test        # python -m pytest -q
    make validate    # 结构校验
    make lint        # ruff check .
    make typecheck   # mypy
    make demo-json   # 离线 demo 的 JSON 输出
    make ci          # 以上五条串起来

---

## 完整运行

这一节是完整链路，前置条件比上面两条复现口径重：需要本地数据（`data/`、`ops/lab/*_cases`）和已生成的制品
（`artifacts/detectors`、`artifacts/templates`、`artifacts/releases`），以及 Docker / WSL 实验台。新克隆只能跑
「A 最简」那三条命令，跑不了这里的采集与评测。

### 1. WSL 故障采集

    bash ops/lab/wsl/reset_volume.sh
    python ops/lab/wsl/run_case.py --fault DN_VOLUME --database runtime/lab/wsl.sqlite3 --require-signal
    python ops/lab/wsl/run_case.py --fault DN_HEARTBEAT --database runtime/lab/wsl.sqlite3 --require-signal
    python ops/lab/wsl/run_case.py --fault NN_SAFE_MODE --database runtime/lab/wsl.sqlite3 --require-signal

### 2. Docker 故障采集

    docker compose -f ops/lab/compose.yaml up -d
    python ops/lab/harness/run_batch.py --real --per-fault 7 --observe 12 --database runtime/lab/real_batch.sqlite3 --require-signal
    python ops/lab/harness/run_batch.py --real --faults NETWORK_PARTITION --per-fault 7 --observe 30 --database runtime/lab/network.sqlite3 --require-signal
    docker compose -f ops/lab/compose.yaml down -v

### 3. 门禁与 event 重放

下面的 `run_gate_batch.py` 是一整条命令（写成一行，PowerShell、cmd、bash 都能直接粘）：

    python ops/lab/harness/run_gate_batch.py --cases ops/lab/wsl_cases --database runtime/lab/events.sqlite3 --source-db runtime/lab/wsl.sqlite3 --source-type wsl --detector artifacts/detectors/wsl_sliding_v4.json --detector-release novelty_wsl_sliding_v4 --template-dir artifacts/templates/wsl --gate-output resources/evaluation/lab/gates.json --window-seconds 60 --window-step 10 --max-rows 500

默认把同一案例/组件、时间重叠或相接的 PASS 窗口合并为一个 event；加 `--no-event-merge` 可关闭，加 `--max-event-span 300` 可调整合并时长上限。

### 4. 评测

注意 `--normal-dir`：`load_normal_windows` 只读该目录**顶层**的 `*.log`，而 `ops/lab/normal/` 里的日志放在
`<批次>/logs/` 下，直接把父目录传进去会得到 0 个正常窗口（检测器退回默认阈值 0.1，窗口全部 PASS）。复现窗口层
指标时请传摊平后的日志目录，生成结果与 `runtime/unified4/windows_*.json` 对照。

    python ops/scripts/evaluate_windows.py --cases ops/lab/wsl_cases --source-type wsl --normal-dir ops/lab/normal --output resources/evaluation/lab/windows.json
    python ops/scripts/evaluate_events.py --gates resources/evaluation/lab/gates.json --database runtime/lab/events.sqlite3 --cases ops/lab/wsl_cases --output resources/evaluation/lab/events.json
    python ops/scripts/evaluate_evidence.py --cases ops/lab/wsl_cases --source-type wsl --output resources/evaluation/lab/evidence.json
    python ops/scripts/evaluate_citations.py --gates resources/evaluation/lab/gates.json --database runtime/lab/events.sqlite3 --cases ops/lab/wsl_cases --output resources/evaluation/lab/citations.json

### 5. 4 类统一评测

    python ops/scripts/evaluate_unified.py --manifest resources/evaluation/unified4/manifest.json --split resources/evaluation/unified4/split.json --root . --output resources/evaluation/unified4/results.json

### 6. 重建 RAG release

    python -m online.knowledge validate --config resources/configs/retrieval.yaml
    python -m online.knowledge build --config resources/configs/retrieval.yaml
    python -m online.knowledge tune --config resources/configs/retrieval.yaml
    python -m online.knowledge publish --config resources/configs/retrieval.yaml

---

## 边界与限制

1. 实验室数据，不是生产准确率
   132 例来自受控注入，不是生产工单；不能把案例多数投票 100% 当成线上效果。20 例分布偏移回归集当前 20/20，但这 20 例已参与本轮信号规则迭代，不是盲测，不能当作跨分布泛化提升。

2. 4 类故障
   只覆盖卷、心跳、安全模式、网络分区；没有 HA failover、block 损坏和多故障叠加。

3. 磁盘 IO 未纳入
   磁盘 IO 与卷故障的只读日志不可区分，已从 4 类统一指标中移除。

4. 案例口径会掩盖波动
   合并事件后 test 的多数投票和所有事件都对都是 60/60；改进前的逐窗口口径下所有事件都对只有 55/60，单窗口诊断仍有波动，合并只是减少重复诊断，不提升单窗口准确率。

5. 正常基线较短
   目前是 30 分钟/20 分钟级正常采集，还没有 24 小时基线。

6. LangGraph 是研究候选后端，不是默认
   默认服务配置（`resources/configs/service.yaml`）不带 `agent_backend`，走 Native 7 节点。框架候选
   `agrfw_9001970e…`（`service_v12_rc1.yaml` 用）状态是 READY_FOR_FLOW_VALIDATION、`production_ready=false`：
   封存集 30/30 与 legacy 报告一致，但 checkpoint 双写、恢复与迁移尚未验证，不能当成生产可用。

7. 只读建议
   所有建议 execution_allowed=false，不自动执行。

8. RAG release 本地生成
   artifacts/releases/kb_v0.1 不提交 Git，新环境需要重新 build/tune/publish。

---

## License

MIT，见 [LICENSE](LICENSE)。
