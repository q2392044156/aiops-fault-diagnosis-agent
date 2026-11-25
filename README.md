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
    │  │  ├─ ingestion/            # 解析适配、canonical、脱敏、窗口
    │  │  └─ case/                 # 事件契约、导入校验、受控实验记录、来源模板与新颖度门禁
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
    │     ├─ platform/             # API、worker、SQLite、UI、MCP、incident 命令、规则检测器
    │     └─ release/
    ├─ ops/
    │  ├─ lab/                     # Docker/WSL 实验台、采集、批量重放
    │  ├─ scripts/                 # 门禁重放、证据/引用/案例评测、服务烟测
    │  ├─ deployment/              # 健康检查与部署辅助
    │  └─ redteam/                 # 红队语料
    ├─ resources/
    │  ├─ configs/                 # Agent、RAG、检索、服务配置
    │  ├─ knowledge/               # 知识卡和知识库
    │  └─ evaluation/              # 冻结协议、切分与评测结果
    ├─ tests/                      # 自动化测试（209 个用例）
    ├─ documentation/              # 架构、实施报告与验收记录
    ├─ demo/                       # 离线端到端演示
    ├─ data/                       # 原始与处理后的日志数据（本地）
    ├─ experiments/                # 评测产物（本地）
    ├─ artifacts/                  # RAG 与发布清单（本地生成）
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
    severity + 关键词规则门禁
            ↓
    PASS 窗口事件化（相接窗口合并）

门禁规则：

- 级别分：FATAL 1.0、ERROR 0.9、WARN 0.6、INFO 0.1、DEBUG 0.05；FATAL/ERROR/WARN 的起始分已经不低于阈值 0.6，所以直接 PASS；
- 关键词分：一行只要命中关键词（`ENOSPC`、`missed liveness deadline`、`safe mode` 等），分数被抬到 `0.6 + 0.05 × 命中个数`（≥ 0.65），因此 INFO/DEBUG 行只有命中关键词才会 PASS；
- 一行取“级别分”和“关键词分”的较大者，会话取其中最高分；分数 ≥ 0.6 且会话不少于 1 行才 PASS；
- 分数落在 [0, 1]，只表示“越接近 1 越异常”，没有校准含义。

同一案例、同一组件、时间重叠或相接的 PASS 窗口合并为一个 event，避免同一段故障重复诊断。实验台还可以按来源单独拟合
模板器（`offline/case/source_templates.py`），用“未见模板比例 + 严重级别优先”做窗口门禁
（`offline/case/novelty.py`）。

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

## 真实案例验证

### 分布偏移回归集（challenge20）

统一 4 类实验台数据的案例多数投票是 60/60，但它和注入脚本、时间窗、日志模板来自同一批。为了回答“换格式、换时间、换主机名、换故障表述后还认不认得”，另构造了 20 个派生案例：

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

这组结果来自信号本体与事件合并的改进：可解释信号覆盖“missed its liveness deadline”“ENOSPC”“Startup guard”等同义表述，按 strongest signal 排序，相接窗口合并为一个事件（57→21）。**但这 20 例已经参与规则迭代，不是盲测 holdout；20/20 只能说明回归通过，不能证明跨分布泛化提升。**

完整说明、复现命令和逐案例结果见 [resources/evaluation/challenge20/README.md](resources/evaluation/challenge20/README.md)。

### 案例、事件与置信区间口径

- 案例级有四种口径：多数投票、首事件、所有事件都对（最差事件）、任一事件；主指标仍是事件级 Macro / Micro；
- 置信区间按故障族分层、以案例为重采样单元做 cluster bootstrap，100% 指标同时保留 Wilson 作参考；
- 事件全部报告为 `DEGRADED_TEMPLATE`，指标反映规则/证据链路，不代表 LLM 生成质量；
- 磁盘 IO 实验因与卷故障日志不可区分，未纳入 4 类指标。

### 服务与 Agent 口径

- W10 独立验收 40 例（12 常规诊断 / 6 正常疑似误告 / 6 证据不足 / 6 高风险 / 4 工具故障 / 4 提示注入 / 2 审批冲突），三次真实 DeepSeek 均值：Task Success 100%、强制复核 Recall 100%、复核 Precision 100%、有效引用率 100%、报告 Schema 通过率 93.33%±11.55%、模板降级率 6.67%；
- 工具自由路由准确率 55% < 80% 门槛，因此默认关闭 LLM 自由路由，编排交给确定性控制器；
- 明细见 `tests/test_w10.py`、[documentation/v1.2_RC1_实施报告.md](documentation/v1.2_RC1_实施报告.md)。

---

## 环境与配置

### 两种复现口径

| 口径 | 额外需要 | 能到什么程度 |
| --- | --- | --- |
| **A 最简**（先跑这个） | Python 3.11 + 能装 pip 包 | 209 个用例全部通过；离线 demo、结构校验可用；静态检查另装 ruff/mypy |
| **B 完整** | 再加 torch / optimum-onnx / transformers | 重建 BGE ONNX 与知识库发布制品 |

v2 不再包含任何训练制品：检测器是 `aiops_diag/platform/release.py` 里的规则实现，服务启动不需要模型文件。
但服务装配仍要读两份发布清单：`artifacts/releases/kb_v0.1`（知识库检索）与 `artifacts/releases/agent_v0.2`
（Agent 发布身份）。`artifacts/` 不提交 Git，新克隆直接起服务会在 `/health/ready` 报清单缺失；离线 demo 与
三条验证命令都不需要它们。

### A 最简：三条命令装上

    python -m pip install -r requirements-framework-lock.txt "pytest>=8,<10"
    python -m pip install -e . --no-deps
    python -m pip check

装完就是三条验证命令，不需要 API Key、不需要 GPU、不写数据库：

    python -m pytest -q                                # 209 passed
    python demo/run_demo.py --json                     # 离线端到端，约 2 秒
    python ops/scripts/validate_project_structure.py   # PASS

pwsh 7 / bash 想一行跑完前三条验证：

    python -m pytest -q && python ops/scripts/validate_project_structure.py && python demo/run_demo.py --json

日常只需要这三条验证命令；`pip check` 装完过一遍就行（若只报 `pipx` 自身的 filelock/packaging
版本冲突，那是环境自带的工具，与项目依赖无关）。

如果 `pip install` 长时间停在“解析依赖”不动（本机 pip 26.3 实测 20 分钟没有任何进展，同一份 lock 用 uv
11 秒装完），可以换成 uv，装的还是同一份 lock：

    uv venv .venv --python 3.11
    uv pip install --python .venv/Scripts/python.exe -r requirements-framework-lock.txt "pytest>=8,<10"
    uv pip install --python .venv/Scripts/python.exe -e . --no-deps

Linux/macOS 把 `--python .venv/Scripts/python.exe` 换成 `--python .venv/bin/python` 即可。

真实案例侧另有一条可复核的重放：`python ops/scripts/replay_cases.py prepare` → 用
`run_gate_batch.py` 重放 132 例 → `python ops/scripts/replay_cases.py verify`，与删除研究训练轨前的
冻结基线逐条比对（事件切分、门禁理由与分数、案例 Top-1）。步骤与实测输出见
[documentation/REPRODUCTION_v2.md](documentation/REPRODUCTION_v2.md)。

### B 完整：一条命令建 conda 环境

    conda env create --file environment.yml
    conda activate aiops-fault-diagnosis-agent

`environment.yml` 里已经带 `-e .[dev,research]`（torch 2.14.1+cu130、transformers、optimum-onnx），
用来把 BGE 模型导出成 ONNX；CPU-only 机器把 `--extra-index-url` 的 `cu130` 换成 `cpu` 即可。

### 环境要求

| 依赖 | 要求 |
| --- | --- |
| Python | 3.11（见 `.python-version`） |
| Conda | 只有 B 口径需要 |
| torch | 只有重建 ONNX 制品需要 |
| Docker | Docker 实验需要 |
| WSL2 + Ubuntu + JDK 11 + Hadoop 3.3.6 | WSL 实验需要 |

### 配置

| 配置 | 作用 |
| --- | --- |
| .env | DeepSeek API Key，离线运行不需要 |
| resources/configs/agent.yaml | 7 节点预算、工具、审批 |
| resources/configs/rag.yaml | RAG Top-K、RRF、BGE |
| resources/configs/query_builder_v1.yaml | 检索式构造（v1.1 候选） |
| resources/configs/retrieval.yaml | 知识库构建与检索协议 |
| resources/configs/service.yaml | 默认服务装配：不带 `agent_backend`，走 Native 7 节点；`detector` 给规则门禁阈值 |
| resources/configs/service_v11_candidate.yaml | v1.1 候选（Native + 检索式查询 + 门禁阈值） |
| resources/configs/service_v12_rc1.yaml | 框架候选 + checkpoint（v1.2 候选：LangGraph + LangChain 报告） |
| resources/configs/service_framework_rc2.yaml | 框架候选（LangGraph）的服务装配 |
| resources/knowledge/ | 知识卡与知识库 |
| artifacts/ | RAG release 与发布清单 |
| runtime/ | SQLite 与运行产物 |

artifacts/、runtime/、data/、experiments/ 和 ops/lab/*_cases/ 不提交 Git。

### 三个常见问题

1. **克隆后 4 条 `test_retrieval*` 报 `Sealed development queries changed`**：密封协议的摘要是按字节算的，
   仓库里存的是 LF；Windows 上 `core.autocrlf=true` 会把工作区改成 CRLF，摘要就对不上。`.gitattributes`
   已经固定 LF，真遇到就 `git config --global core.autocrlf false` 后重新 `git checkout -- resources`。
2. **服务起不来，`/health/ready` 返回失败**：先看 `status.ready_error`。v2 有四类失败来源：`service.yaml`
   解析失败、SQLite 打不开、RAG 发布清单缺失（`artifacts/releases/kb_v0.1`，重建知识库发布即可）、Agent 发布
   清单缺失或指纹漂移（`artifacts/releases/agent_v0.2`；若报 `Agent configuration changed after publication`，
   说明 `resources/configs/agent.yaml` 或 `src/online/diagnosis/*.py` 在清单冻结后改过，重发一次 Agent 清单即可）。
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

## 完整实现

这一节是从空环境走到「跑出案例、重放门禁、算出指标」的完整过程，每一步都给命令和本机实测输出。
前四小节（1–4）只需要 Python，新克隆照做即可；5 节以后需要本地数据、Docker / WSL 实验台，以及
gitignore 里的 `artifacts/`（门禁探测器 `artifacts/detectors/*_sliding_v4.json`、模板
`artifacts/templates/*`）。完整跑一遍约 1.5 小时，主要时间在故障注入的观测窗口。

### 1. 复现环境

| 组件 | 本机实测 | 用途 |
| --- | --- | --- |
| 操作系统 | Windows 11 + PowerShell 7 | 主环境 |
| Python | 3.11.16（由 uv 提供，见 `.python-version`） | 全部阶段 |
| uv | 0.12.11 | 建 venv、装锁定依赖 |
| Docker | 29.8.2（Docker Desktop） | Docker 实验台（1 NN + 3 DN） |
| WSL2 | Ubuntu-24.04，Hadoop 3.3.6 + JDK 11 | WSL 实验台 |
| GPU | 不需要（torch 只在重建 BGE ONNX 时需要） | B 口径 |

### 2. 从零装环境（A 最简，实测约 1 分钟）

    uv venv .venv --python 3.11 --seed
    uv pip install --python .\.venv\Scripts\python.exe -r requirements-framework-lock.txt "pytest>=8,<10"
    uv pip install --python .\.venv\Scripts\python.exe -e . --no-deps
    .\.venv\Scripts\python.exe -m pip check

Linux / macOS 把 `--python .\.venv\Scripts\python.exe` 换成 `--python .venv/bin/python`。

实测：`uv venv` 落到 CPython 3.11.16；`uv pip install` 11 秒装完并打印 `Installed 1 package in 13ms`
（可编辑安装）；`pip check` → `No broken requirements found.`。用 pip 装同一份 lock 在本机会卡在
依赖解析（20 分钟无进展），原因与绕过方式见第 11 节第 1 条。

### 3. 三条验证命令（实测输出）

    .\.venv\Scripts\python.exe -m pytest -q
    # 209 passed, 3 warnings in 37.49s

    .\.venv\Scripts\python.exe demo\run_demo.py --json
    # {
    #   "counts": {"total_lines": 12, "parsed_lines": 10, "quarantined_lines": 2,
    #              "session_count": 3, "anomaly_count": 1, "event_count": 1},
    #   "event_id": "evt_9658dab23fa9c49cae2a7880",
    #   "diagnosis_id": "dia_8487f2a6c0a63b93c43d83e3",
    #   "report_id": "irpt_462a496786e3b0acd0ae757b",
    #   "diagnosis_status": "DEGRADED_TEMPLATE",
    #   "confidence_level": "low",
    #   "requires_review": true,
    #   "review_reasons": ["low_confidence"],
    #   "tool_calls": 7, "evidence": 7,
    #   "illegal_citations": 0, "executable_advice": 0,
    #   "approval_status": "APPROVED", "final_status": "APPROVED_REPORT",
    #   "llm_calls": 0, "tokens": 0, "estimated_cost_cny": 0.0,
    #   "elapsed_seconds": 1.372
    # }

    .\.venv\Scripts\python.exe ops\scripts\validate_project_structure.py
    # {
    #   "schema_version": 1,
    #   "status": "PASS",
    #   "module_directory_count": 17,
    #   "python_file_count": 165,
    #   "errors": []
    # }

demo 的判定要点：12 行日志里 10 行解析成功、2 行进隔离区，聚成 3 个会话，规则门禁挑出 1 个异常会话
并合成 1 个 event；7 次只读工具调用、7 条证据，0 条非法引用、0 条可执行建议；因为没有 Key 走模板链路，
所以是 `DEGRADED_TEMPLATE` + `requires_review=true`，但复核通过后 final 仍是 `APPROVED_REPORT`。

### 4. 静态检查（实测）

    uv pip install --python .\.venv\Scripts\python.exe "ruff==0.17.5" "mypy==2.4.1"
    .\.venv\Scripts\python.exe -m ruff check .
    # All checks passed!
    .\.venv\Scripts\python.exe -m mypy
    # Success: no issues found in 6 source files

结构校验是另一套规则，和这两条互不替代：模块目录登记、每个 `.py` 都要在模块 README 里列到、模块
docstring 用中文、禁止 `# 方法说明：` 一类机械注释标签、mypy 边界清单里的函数必须写返回标注。

### 5. Docker 实验台（1 NameNode + 3 DataNode）

`ops/lab/compose.yaml` 定义 4 个服务，镜像 `apache/hadoop:3.3.6`，同一 bridge 网络 `hdfs`：

| 服务 | 容器名 | 存储 | 说明 |
| --- | --- | --- | --- |
| namenode | aiops-lab-namenode | `namenode-data` 命名卷 | 暴露 9870（Web UI）/ 9000（RPC） |
| datanode1 | aiops-lab-dn1 | 128 MB tmpfs | 造卷满最快，一个 `dd` 就 ENOSPC |
| datanode2 | aiops-lab-dn2 | `dn2-data` 命名卷 | 心跳丢失 / 安全模式注入 |
| datanode3 | aiops-lab-dn3 | `dn3-data` 命名卷 | 同上 |

启动与健康校验：

    docker compose -f ops/lab/compose.yaml config --quiet     # 语法自检，无输出即通过
    docker compose -f ops/lab/compose.yaml up -d
    docker ps --filter name=aiops-lab --format '{{.Names}}\t{{.Status}}'
    # aiops-lab-namenode ... 0.0.0.0:9870->9870, 0.0.0.0:9000->9000
    # aiops-lab-dn1 / dn2 / dn3  Up
    curl -s -o NUL -w "%{http_code}" http://127.0.0.1:9870/     # 200
    docker exec aiops-lab-namenode hdfs dfs -ls /               # 有 /aiops-normal、/lab 即正常

注入脚本挂在容器内 `/lab/inject`（`dn_volume_full.sh`、`dn_volume_recover.sh`、
`nn_safemode_enter.sh`、`nn_safemode_leave.sh`），起停脚本在 `/lab/bin`，都由 `run_batch.py` 调用，
一般不用手敲。

停止：只想暂停用 `docker compose -f ops/lab/compose.yaml stop`（保留 namenode 卷里的 HDFS 数据）；
要彻底清空用 `down -v`，会删掉 `namenode-data` 卷，下次启动是空集群。

### 6. 采集故障案例

Docker 侧（21 例，每类 7 例；卷/心跳/安全模式各观测 12 秒，网络分区 30 秒）：

    python ops/lab/harness/run_batch.py --real --per-fault 7 --observe 12 --database runtime/lab/real_batch.sqlite3 --require-signal
    python ops/lab/harness/run_batch.py --real --faults NETWORK_PARTITION --per-fault 7 --observe 30 --database runtime/lab/network.sqlite3 --require-signal

WSL 侧（单机 HDFS，先重置卷再逐类注入）：

    bash ops/lab/wsl/reset_volume.sh
    python ops/lab/wsl/run_case.py --fault DN_VOLUME --database runtime/lab/wsl.sqlite3 --require-signal
    python ops/lab/wsl/run_case.py --fault DN_HEARTBEAT --database runtime/lab/wsl.sqlite3 --require-signal
    python ops/lab/wsl/run_case.py --fault NN_SAFE_MODE --database runtime/lab/wsl.sqlite3 --require-signal

产物：`ops/lab/real_batch_cases/<id>/`、`ops/lab/wsl_cases/<id>/`、`ops/lab/network_cases/<id>/`，
每例含 `incident.json`（脱敏后的事件记录）、`map.json`、`evidence/logs/*.log`、`evidence/metrics/*.csv`；
案例入库信息在 `runtime/lab/*.sqlite3`。

### 7. 门禁与 event 重放

需要 `artifacts/detectors/*_sliding_v4.json` 与 `artifacts/templates/*`（都不在 Git 里，见第 9 节）。
`run_gate_batch.py` 写成一行，PowerShell / cmd / bash 都能直接粘：

    python ops/lab/harness/run_gate_batch.py --cases ops/lab/wsl_cases --database runtime/lab/events.sqlite3 --work runtime/lab/gate_work --output runtime/lab/gate_output --source-db runtime/lab/wsl.sqlite3 --source-type wsl --detector artifacts/detectors/wsl_sliding_v4.json --detector-release novelty_wsl_sliding_v4 --template-dir artifacts/templates/wsl --gate-output resources/evaluation/lab/gates.json --window-seconds 60 --window-step 10 --max-rows 500

它逐案重放「解析 → 60s/10s 窗口 → 门禁 → 事件合并 → 诊断 → 报告」，实测 WSL 68 例全部 PASS，
gate_reason 集中在 `novel_info`（57）与 `novel_warn`（11），每案 1–3 个 event。

探测器可以重新拟合：先用 `capture_normal.py` 采正常窗口，再跑

    python ops/lab/harness/evaluate_detector.py --cases ops/lab/wsl_cases --source-type wsl --normal-dir <正常日志目录> --output resources/evaluation/lab/detector_wsl_steady.json --save artifacts/detectors/wsl_sliding_v4.json

默认把同一案例/组件、时间重叠或相接的 PASS 窗口合并成一个 event；加 `--no-event-merge` 关闭，
`--max-event-span 300` 调整合并时长上限。重放 132 例的完整口径见
[documentation/REPRODUCTION_v2.md](documentation/REPRODUCTION_v2.md)。

### 8. 真实案例评测

    python ops/scripts/evaluate_challenge20.py
    python ops/scripts/evaluate_incidents.py --database runtime/lab/wsl.sqlite3
    python ops/scripts/evaluate_evidence.py --cases ops/lab/wsl_cases --source-type wsl --output resources/evaluation/lab/evidence.json
    python ops/scripts/evaluate_citations.py --gates resources/evaluation/lab/gates.json --database runtime/lab/events.sqlite3 --cases ops/lab/wsl_cases --output resources/evaluation/lab/citations.json

`evaluate_challenge20.py` 实测输出：`cases 20`、`events 21`、`report_modes {"DEGRADED_TEMPLATE": 21}`，
四组各 5/5（`paraphrase_distractor` 事件 6/6），卷 7/7、心跳 7/7、安全模式 6/6。

它默认读 `runtime/challenge20/events_committed.sqlite3`，并把结果写回被 Git 跟踪的
`resources/evaluation/challenge20/results.json`；换个环境想只看结果，加 `--db runtime/verify/challenge20.sqlite3
--output runtime/verify/challenge20.json`，避免改动仓库文件。

### 9. 重建 RAG 发布制品（B 口径）

服务装配要读 `artifacts/releases/kb_v0.1`（知识库）与 `artifacts/releases/agent_v0.2`（Agent 发布身份），
两者都不提交 Git。知识库发布用 `online.knowledge`：

    python -m online.knowledge validate --config resources/configs/retrieval.yaml
    python -m online.knowledge build --config resources/configs/retrieval.yaml      # 104 卡切 154 chunk
    python -m online.knowledge tune --config resources/configs/retrieval.yaml       # 标定门禁阈值
    python -m online.knowledge publish --config resources/configs/retrieval.yaml
    python -m online.knowledge verify --config resources/configs/retrieval.yaml

`build`/`tune` 需要 `transformers` / `optimum-onnx` / `torch`（`environment.yml` 的 `research` extras）来导出
BGE ONNX；只想跑前面的 A 口径不需要装。发布完可以校验服务装配、起服务：

    python -m aiops_diag.platform verify --config resources/configs/service.yaml
    # {"verified": true, "release_id": "v0.3_rules", "model_id": "severity_rule"}
    python -m aiops_diag.platform serve --config resources/configs/service.yaml      # API + UI
    python -m aiops_diag.platform worker --config resources/configs/service.yaml     # 后台 worker

### 10. 走一遍完整链路（服务侧）

    # 上传一批日志（multipart 字段名固定为 file），返回 task_id / batch_id
    curl -X POST http://127.0.0.1:8000/api/v1/batches/uploads -H "Idempotency-Key: demo-1" -F "file=@<日志文件>"
    # 等 worker 处理完，查任务、批次与事件
    curl http://127.0.0.1:8000/api/v1/tasks/<task_id>
    curl http://127.0.0.1:8000/api/v1/batches/<batch_id>
    curl "http://127.0.0.1:8000/api/v1/events?batch_id=<batch_id>"
    # 选一个 event 起诊断（B 完成后不会自动建诊断，必须显式提交）
    curl -X POST http://127.0.0.1:8000/api/v1/diagnoses -H "Content-Type: application/json" -H "Idempotency-Key: diag-1" -d "{\"event_id\": \"<event_id>\"}"
    curl http://127.0.0.1:8000/api/v1/reports/<report_id>
    # 人工复核：需要复核员 token、Idempotency-Key，以及审批单上的 report_hash / revision
    curl -X POST http://127.0.0.1:8000/api/v1/approvals/<approval_id>/decision -H "Authorization: Bearer <复核员 token>" -H "Idempotency-Key: approval-1" -H "Content-Type: application/json" -d "{\"decision\": \"approve\", \"report_hash\": \"<report_hash>\", \"revision\": <revision>}"

复核接口的 `decision` 只接受 `approve` / `reject` / `request_more_evidence`；复核员身份来自
`AIOPS_REVIEWER_REGISTRY_FILE` 指向的注册表，没配时会返回 503 `REVIEWER_AUTH_UNAVAILABLE`。

只想一条命令看完 B→C，用离线 demo：`python demo/run_demo.py`（不写数据库、不需要 Key）。

### 11. 复现时会踩的坑

1. **`pip install` 卡在依赖解析**：本机 pip 26.3 对 `requirements-framework-lock.txt` 解析 20 分钟没有
   任何产出；同一份 lock 用 uv 11 秒装完。改用第 2 节的 uv 命令，装的依赖完全一致。
2. **Windows 上敲 `python` 弹出应用商店**：那是 `WindowsApps` 下的占位符。用 `.venv\Scripts\python.exe`
   绝对路径，或 `py -3.11`。
3. **克隆后 4 条 `test_retrieval*` 报 `Sealed development queries changed`**：密封摘要按字节算，仓库是 LF；
   `core.autocrlf=true` 会把工作区改成 CRLF。`.gitattributes` 已固定 LF，真遇到就
   `git config --global core.autocrlf false` 后重新 `git checkout -- resources`。
4. **`evaluate_challenge20.py` 找不到 DB 或改动了仓库文件**：默认 DB 在 `runtime/`（不入库），输出会回写
   被跟踪的 `results.json`；用 `--db` / `--output` 指到 `runtime/` 下。
5. **`/health/ready` 失败**：看 `status.ready_error`，四类来源——`service.yaml` 解析、SQLite 打不开、
   RAG 清单缺失（`artifacts/releases/kb_v0.1`）、Agent 清单缺失或指纹漂移（`artifacts/releases/agent_v0.2`，
   报 `Agent configuration changed after publication` 时重发清单）。
6. **`run_gate_batch.py` 缺参数报 `--work, --output`**：这两个是必填，指到 `runtime/lab/` 下的临时目录。
7. **PowerShell 5.1 用 `Out-File -Encoding utf8` 改文件会写 BOM**，导致 `SyntaxError: invalid
   non-printable character U+FEFF`；改文件用 `[IO.File]::WriteAllText($p, $text, (New-Object Text.UTF8Encoding($false)))`。

### 12. 一次完整复现的检查清单

| 步骤 | 命令 | 期望 | 实测耗时 |
| --- | --- | --- | --- |
| 建环境 | 第 2 节三条 uv 命令 | `pip check` 无冲突 | 约 1 分钟 |
| 用例 | `python -m pytest -q` | 209 passed | 37 秒 |
| 离线 demo | `python demo/run_demo.py --json` | `APPROVED_REPORT`、0 非法引用 | 1.4 秒 |
| 结构校验 | `python ops/scripts/validate_project_structure.py` | `status: PASS`、17 目录 / 165 py | 1 秒 |
| 静态检查 | `python -m ruff check .` / `python -m mypy` | 全通过 | 各 2 秒 |
| 起实验台 | `docker compose -f ops/lab/compose.yaml up -d` | 4 容器 Up、9870 返回 200 | 25 秒 |
| Docker 采集 | 第 6 节两条 `run_batch.py` | 每类 7 例、`--require-signal` 通过 | 约 25 分钟 |
| WSL 采集 | 第 6 节三条 `run_case.py` | 每类至少 1 例带信号 | 约 10 分钟 |
| 门禁重放 | 第 7 节 `run_gate_batch.py` | 案例全 PASS、产出 event/report | 约 3 分钟 |
| 评测 | 第 8 节四个 `evaluate_*.py` | challenge20 20/20、事件 21/21 | 约 1 分钟 |
| 清场 | `docker compose -f ops/lab/compose.yaml down -v` | 容器与卷清空 | 5 秒 |

---

## 边界与限制

1. 实验室数据，不是生产准确率
   132 例来自受控注入，不是生产工单；不能把案例多数投票 100% 当成线上效果。20 例分布偏移回归集当前 20/20，但这 20 例已参与规则迭代，不是盲测。

2. 4 类故障
   只覆盖卷、心跳、安全模式、网络分区；没有 HA failover、block 损坏和多故障叠加。

3. 磁盘 IO 未纳入
   磁盘 IO 与卷故障的只读日志不可区分，已从 4 类指标中移除。

4. 规则门禁取代训练模型
   在线检测只做“日志级别 + 关键词”的确定性打分，没有概率校准，也没有学习到的模式；换一套日志格式就要重新核对关键词表。

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
