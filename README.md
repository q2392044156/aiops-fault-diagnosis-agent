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
    每个 PASS 窗口创建一个 event

门禁规则：

- ERROR/FATAL 优先 PASS；
- WARN 只有新模板或频次超过正常基线才 PASS；
- INFO 用 novelty 兜底；
- 不同来源使用不同模板和冻结阈值。

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

- 证据选择：组件关注、信号/严重度/稀有度/时间评分、堆栈与重复消息去重、50 行 + 2000 token 预算；
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

| 集合 | 案例 | 事件 | 案例 Top-1 | 事件 Top-1 | Macro Event |
| --- | --- | --- | --- | --- | --- |
| test | 60 | 429 | 60/60 = 100% | 423/429 = 98.60% | 0.9783 |
| train | 72 | 303 | 71/72 = 98.61% | 294/303 = 97.03% | 0.9722 |

test 每类：

| 故障族 | 案例 | 事件 | 案例 Top-1 | 事件 Top-1 |
| --- | --- | --- | --- | --- |
| 卷故障 | 15 | 43 | 15/15 | 43/43 |
| 心跳丢失 | 15 | 69 | 15/15 | 63/69 = 91.3% |
| 安全模式 | 15 | 32 | 15/15 | 32/32 |
| 网络分区 | 15 | 285 | 15/15 | 285/285 |

test 混淆矩阵四类全部落在对角线上，误判 0。

### 检测门禁

| 指标 | Docker | WSL |
| --- | --- | --- |
| 正常窗口 FPR | 0/166 | 0/74 |
| 正常窗口数 | 553 | 244 |
| 窗口 Recall | 275/294 | 212/212 |
| 案例 Recall | 80/81 | 68/68 |

### 说明

- 案例级是 Any-Event 口径，事件级更严格；
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
   132 例来自受控注入，不是生产工单；不能把 100% 案例 Top-1 当成线上效果。

2. 4 类故障
   只覆盖卷、心跳、安全模式、网络分区；没有 HA failover、block 损坏和多故障叠加。

3. 磁盘 IO 未纳入
   磁盘 IO 与卷故障的只读日志不可区分，已从 4 类统一指标中移除。

4. 事件级低于案例级
   事件级 98.60%，案例级 100%；单窗口诊断仍有波动。

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
