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
    │  │  ├─ capture/              # 采集入口，实际脚本在 ops/lab
    │  │  ├─ ingestion/            # adapter、canonical、窗口、incident
    │  │  ├─ detection/            # Drain3、severity-first 门禁
    │  │  └─ evaluation/           # 红队、轨迹、框架评测
    │  ├─ online/                  # 在线诊断流程
    │  │  ├─ diagnosis/            # 7 节点引擎、证据选择、工具
    │  │  ├─ knowledge/            # 104 卡 RAG
    │  │  └─ reporting/            # 报告 Schema 入口
    │  └─ aiops_diag/              # 共享基础设施 + 旧导入兼容层
    │     ├─ common.py
    │     ├─ platform/             # API、worker、SQLite、UI、MCP
    │     └─ release/
    ├─ ops/
    │  ├─ lab/                     # Docker/WSL 实验台、采集、批量重放
    │  └─ scripts/                 # 门禁、事件、证据、引用评测
    ├─ resources/
    │  ├─ configs/                 # Agent、RAG、服务配置
    │  ├─ knowledge/               # 知识卡和知识库
    │  └─ evaluation/              # 冻结切分与结果
    ├─ tests/                      # 自动化测试
    ├─ demo/                       # 离线端到端演示
    ├─ artifacts/                  # 检测器/RAG release（本地生成）
    └─ runtime/                    # SQLite、临时运行数据（本地生成）

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

| 集合 | 案例 | 事件 | 案例多数投票 | 案例首事件 | 案例所有事件都对 | 事件 Top-1 | Macro Event |
| --- | --- | --- | --- | --- | --- | --- | --- |
| test | 60 | 143 | 60/60 = 100% | 60/60 = 100% | 60/60 = 100% | 143/143 = 100% | 1.0000 |
| train | 72 | 156 | 71/72 = 98.61% | 71/72 = 98.61% | 71/72 = 98.61% | 155/156 = 99.36% | 0.9949 |

事件数是合并后的数量：同一案例、同一组件、时间重叠或相接的 PASS 窗口会合并为一个事件，避免同一段故障被重复诊断。改进前的逐窗口结果为 test 429、train 303 个事件，合并后为 test 143、train 156；门禁和窗口召回不受影响。

“案例所有事件都对”等价于最差事件口径；多数投票和首事件会掩盖案例内单个错误事件。

test 每类：

| 故障族 | 案例 | 事件 | 案例多数投票 | 案例所有事件都对 | 事件 Top-1 |
| --- | --- | --- | --- | --- | --- |
| 卷故障 | 15 | 31 | 15/15 | 15/15 | 31/31 |
| 心跳丢失 | 15 | 37 | 15/15 | 15/15 | 37/37 |
| 安全模式 | 15 | 30 | 15/15 | 15/15 | 30/30 |
| 网络分区 | 15 | 45 | 15/15 | 15/15 | 45/45 |

test 混淆矩阵四类全部落在对角线上，案例级误判 0。

置信区间与报告路径：

- 案例多数投票 95% Wilson CI [0.9398, 1.0]；60/60 时非参数 cluster bootstrap 会退化为 [1.0, 1.0]，因此同时保留 Wilson 作参考；
- 案例所有事件都对、事件级、Macro Event 的 cluster 95% CI 均为 [1.0, 1.0]，同样是 100% 指标的边界，不能理解为“零风险”；
- 143/143 测试报告为 `DEGRADED_TEMPLATE`，当前指标主要反映规则/模板链路，不代表 LLM 生成质量；
- test 无错误事件；train 仅 1 个心跳事件无候选，明细见 `resources/evaluation/unified4/results.json` 的 `error_events`。

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

### 说明

- 主指标看 Macro Event 与每类事件级，同时报告案例多数投票、首事件、所有事件都对、任一事件四种口径；
- 置信区间按故障族分层、以案例为重采样单元做 cluster bootstrap；100% 指标在非参数 bootstrap 下会退化为边界，同时保留 Wilson；
- 网络分区是独立批次，已并入 4 类统一切分；
- 磁盘 IO 实验因与卷故障日志不可区分，未纳入 4 类指标；
- 旧 v2 的 149 例、466 事件是历史口径，不再作为当前统一结果。

---

## 环境与配置

### 环境要求

| 依赖 | 要求 |
| --- | --- |
| Python | 3.11 |
| Conda | 推荐 |
| Docker | Docker 实验需要 |
| WSL2 + Ubuntu | WSL 实验需要 |
| JDK 11 + Hadoop 3.3.6 | WSL 实验需要 |

### 安装

    conda env create --file environment.yml
    conda run --name aiops-fault-diagnosis-agent python -m pip install -r requirements-framework-lock.txt
    conda run --name aiops-fault-diagnosis-agent python -m pip install -e ".[dev,framework]" --no-deps
    conda run --name aiops-fault-diagnosis-agent python -m pip check

需要重建 ONNX/BGE 制品时再安装 research 依赖：

    conda run --name aiops-fault-diagnosis-agent python -m pip install -e ".[dev,framework,research]" --no-deps

### 配置

| 配置 | 作用 |
| --- | --- |
| .env | DeepSeek API Key，离线运行不需要 |
| resources/configs/agent.yaml | 7 节点预算、工具、审批 |
| resources/configs/rag.yaml | RAG Top-K、RRF、BGE |
| resources/configs/service_v12_rc1.yaml | API/worker/UI 服务 |
| resources/knowledge/ | 知识卡与知识库 |
| artifacts/ | 检测器、模板、RAG release |
| runtime/ | SQLite 与运行产物 |

artifacts/、runtime/、data/、experiments/ 和 ops/lab/*_cases/ 不提交 Git。

---

## 快速运行

### 离线 Demo（无需 API Key）

    conda run --name aiops-fault-diagnosis-agent python demo/run_demo.py

机器可读：

    conda run --name aiops-fault-diagnosis-agent python demo/run_demo.py --json

预期输出包含 diagnosis_status、final_status=APPROVED_REPORT、工具调用次数和引用数量。

### 测试与结构校验

    conda run --name aiops-fault-diagnosis-agent python -m pytest -q --basetemp=.pytest-tmp
    conda run --name aiops-fault-diagnosis-agent python ops/scripts/validate_project_structure.py

### 在线 Demo（需要 Key）

    conda run --name aiops-fault-diagnosis-agent python demo/run_demo.py --online

---

## 完整运行

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

    python ops/lab/harness/run_gate_batch.py ^
      --cases ops/lab/wsl_cases ^
      --database runtime/lab/events.sqlite3 ^
      --source-db runtime/lab/wsl.sqlite3 ^
      --source-type wsl ^
      --detector artifacts/detectors/wsl_sliding_v4.json ^
      --detector-release novelty_wsl_sliding_v4 ^
      --template-dir artifacts/templates/wsl ^
      --gate-output resources/evaluation/lab/gates.json ^
      --window-seconds 60 --window-step 10 --max-rows 500

默认把同一案例/组件、时间重叠或相接的 PASS 窗口合并为一个 event；加 `--no-event-merge` 可关闭，加 `--max-event-span 300` 可调整合并时长上限。

### 4. 评测

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

6. LangGraph 未对齐
   当前主线是 Native 7 节点；LangGraph 仍有 parity 回归。

7. 只读建议
   所有建议 execution_allowed=false，不自动执行。

8. RAG release 本地生成
   artifacts/releases/kb_v0.1 不提交 Git，新环境需要重新 build/tune/publish。

---

## License

MIT，见 [LICENSE](LICENSE)。
