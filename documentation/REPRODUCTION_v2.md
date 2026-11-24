# 真实案例复现记录（v2）

> 分支 `v2`（提交 `6820429`）删除了研究训练轨之后，本文记录如何把 **132 例真实案例**完整重放一遍，
> 并把结果与删除前冻结的基线逐条比对。所有命令都在仓库根目录执行，Windows PowerShell 与 bash 通用。
> 分支名 `v1` 已于 2026-11-24 重命名为 `v2`（`v1` 预留给 main 的发布口径），提交历史与本文所有数字不变。

## 0. 这份文档证明什么

1. 132 例真实案例在 `v2` 上**仍然完整存在**，只是不在 Git 里（`ops/lab/*` 被 `.gitignore` 忽略）；
2. 案例侧链路（窗口切分 → 模板新颖度门禁 → 事件合并 → 根因信号 → 报告）**逐条复现**删除前的基线：
   132 例的事件切分、门禁理由、门禁分数、案例 Top-1 全部一致；
3. 哪一部分**不再复现**（检测器训练/评测指标），以及为什么它随研究轨一起移除。

复现脚本：`ops/scripts/replay_cases.py`，子命令 `prepare`（准备 case 集）与 `verify`（与基线比对）。

## 1. 环境

| 项 | 值 |
|---|---|
| Python | 3.11.16（`uv venv .venv --python 3.11`） |
| 依赖 | `requirements-framework-lock.txt` + `pip install -e . --no-deps` + `pytest>=8,<10` |
| 复现口径 | README 的「A 最简」：不含 torch / optimum-onnx |
| 自检 | `python -m pytest -q` → 209 passed；`python ops/scripts/validate_project_structure.py` → PASS |

`v2` 不再需要任何训练制品（`experiments/`、`artifacts/releases/v1.0_service`）就能起服务：
`python -m aiops_diag.platform verify --config resources/configs/service.yaml`
→ `{"verified": true, "release_id": "v0.3_rules", "model_id": "severity_rule"}`。

## 2. 数据：132 例从哪来

132 例是"清洗后"的评测集，分布在本地案例目录里（`ops/lab/*`，被 `.gitignore` 忽略，须由实验台采集产生）：

| 来源 | 目录 | 例数 | 故障族 |
|---|---|---|---|
| Docker 实验台 | `ops/lab/real_batch_cases` | 60 | 卷 7 / 心跳 27 / 安全模式 26 |
| WSL 单机 | `ops/lab/wsl_cases` | 30 | 心跳 10 / 安全模式 20 |
| WSL 卷故障 | `ops/lab/recaptured_cases/wsl_volume` | 21 | 卷 21 |
| 网络分区 | `ops/lab/network_cases` | 21 | 网络 21 |
| **合计** | | **132** | 卷 28 / 心跳 37 / 安全模式 46 / 网络 21 |

本地还有另外几组集（不在 132 内）：`wsl_cases` 的 38 个卷案例、`ops/lab/cases` 21 个早期案例、
`disk_io_cases` 20 例、`real_cases` 1 例——共 212 个 `incident.json`，全部能通过 `validate_incident`。

**筛选依据不是目录名，而是两份 source DB 的 `incident_registry`**：
`runtime/unified4/docker_source.sqlite3`（81 行）与 `runtime/unified4/wsl_source.sqlite3`（51 行），
合计 81 + 51 = 132。这两份 DB 也在 `runtime/`（gitignored），是产生基线那次运行的存档。

## 3. 冻结基线（不可重新拟合）

| 制品 | 位置 | 作用 | 是否在 Git |
|---|---|---|---|
| 事件基线 | `resources/evaluation/unified4/{docker,wsl}_gates.json` | 每案的窗口门禁决策与事件切分 | 是 |
| 指标基线 | `resources/evaluation/unified4/results.json` | test/train 的案例与事件指标 | 是 |
| 切分清单 | `resources/evaluation/unified4/split.json` | test 60 / train 72，`test_per_class` 15，`split_hash` | 是 |
| 窗口门禁模型 | `artifacts/detectors/{docker,wsl}_sliding_v4.json` | `TemplateNoveltyDetector` 的模板集与阈值 | 否（`artifacts/` 被忽略） |
| 来源模板 | `artifacts/templates/{docker_container,wsl}/` | Drain3 模板器快照 | 否 |

探测器与模板**必须在产生基线的机器上取回**：重新拟合只能得到近似结果，不保证逐位一致。

## 4. 复现步骤

### 4.1 准备 132 例的 case 集

```powershell
python ops/scripts/replay_cases.py prepare --output runtime/repro
```

输出：

```text
docker: 81 cases -> runtime\repro\cases_docker81
wsl: 51 cases -> runtime\repro\cases_wsl51
```

它按两份 source DB 的 `incident_registry` 取 id，在 `ops/lab` 下找到对应 `incident.json`，
复制成 `runtime/repro/cases_docker81`（81）与 `runtime/repro/cases_wsl51`（51），并写出 `ids_docker.json` / `ids_wsl.json`。
**原始案例目录不会被改动**；行数不等于 81/51、或有 id 在本地找不到时会直接失败并说明原因。

### 4.2 重放（两条命令）

```powershell
python ops/lab/harness/run_gate_batch.py --cases runtime/repro/cases_docker81 `
  --database runtime/repro/docker_run2.sqlite3 --work runtime/repro/work_docker2 `
  --output runtime/repro/docker_eval2 --source-db runtime/unified4/docker_source.sqlite3 `
  --source-type docker_container --detector artifacts/detectors/docker_sliding_v4.json `
  --template-dir artifacts/templates/docker_container `
  --gate-output runtime/repro/docker_gates2.json --ids runtime/repro/ids_docker.json

python ops/lab/harness/run_gate_batch.py --cases runtime/repro/cases_wsl51 `
  --database runtime/repro/wsl_run2.sqlite3 --work runtime/repro/work_wsl2 `
  --output runtime/repro/wsl_eval2 --source-db runtime/unified4/wsl_source.sqlite3 `
  --source-type wsl --detector artifacts/detectors/wsl_sliding_v4.json `
  --template-dir artifacts/templates/wsl `
  --gate-output runtime/repro/wsl_gates2.json --ids runtime/repro/ids_wsl.json
```

每一例会依次走：解析 → 60s/10s 滑窗 → 模板新颖度门禁 → 事件合并 → 根因诊断 → 报告，
结束时自动调用 `ops/scripts/evaluate_incidents.py` 产出 `*_eval2.json`。
每份约 4–5 分钟（81 例 / 51 例，含诊断）。

### 4.3 与基线比对

```powershell
python ops/scripts/replay_cases.py verify --replay runtime/repro --reference resources/evaluation/unified4
```

实测输出（退出码 0 才算通过）：

```text
docker: cases 81 / 81, events 202 / 202, diffs 0 -> PASS
wsl: cases 51 / 51, events 97 / 97, diffs 0 -> PASS
split: stratified_by_family_source / hash c7e3bef450ddfb08
  test_cases: replay 60 / baseline 60 -> PASS
  test_events: replay 143 / baseline 143 -> PASS
  test_top1: replay 60 / baseline 60 -> PASS
  train_cases: replay 72 / baseline 72 -> PASS
  train_events: replay 156 / baseline 156 -> PASS
  train_top1: replay 71 / baseline 71 -> PASS

PASS: event segmentation, gate reasons/scores and case top-1 all match the frozen baseline.
```

## 5. 「0 差异」到底比了什么

`verify` 逐案比对三样东西，任一不同即 FAIL 并打印具体案例与字段：

| 比对项 | 粒度 | 基线字段 |
|---|---|---|
| 每案事件数 | 132 个案例 | `events` 数组长度 |
| 顶层门禁理由 | 132 个案例 | `gate_reason` |
| 逐事件的门禁理由与分数 | 299 个事件 | `events[].gate_reason` / `events[].gate_score`（浮点按 1e-9 容差） |

再比对 test/train 两个切分的案例数、事件数、案例 Top-1，全部来自 `results.json` 的计数字段。

| 指标 | 删除前（`results.json`） | `v2` 重放 |
|---|---|---|
| 事件总数 | 299（test 143 + train 156） | 299（143 + 156） |
| 案例 Top-1（test） | 60/60 = 1.0，CI [0.9398, 1.0] | 60/60 |
| 案例 Top-1（train） | 71/72 = 0.9861，CI [0.9254, 0.9975] | 71/72 |
| 唯一漏例 | `inc_wsl_heartbeat_20261028182517_df45`（rank 空） | 同一例 |
| 分组案例 Top-1 | — | docker 1.0（CI [0.9547, 1.0]）/ wsl 0.9804（CI [0.897, 0.9965]） |
| MTTD | docker 49.8s | 49.8s |
| 报告模式 | 全部 `DEGRADED_TEMPLATE` | 全部 `DEGRADED_TEMPLATE` |

## 6. 前提与坑

- **探测器必须用 `*_sliding_v4.json`**。换成 `docker_container.json` / `wsl.json` 时门禁决策仍是全 PASS、
  案例 Top-1 仍是 1.0，但事件切分从 3 个变 2 个、`gate_score` 从 0.5333 变 0.1935（docker），
  wsl 的事件数从 97 掉到 87、10 个案的 `gate_reason` 漂移——**事件级指标会静默偏移**，所以模型制品要按名字冻结。
- `artifacts/`、`runtime/`、`experiments/`、`data/` 都在 `.gitignore` 里：新克隆只有代码与 `resources/` 基线，
  没有探测器、模板与案例，必须从原机器补齐。
- `run_gate_batch.py` 必须给 `--work` 与 `--output`（旧 README 漏参数，已在 v2 修正）。
- WSL 的卷故障案例缺 `fault_start` 时间戳，MTTD 为 `N/A`，属数据本身缺字段，不是链路问题。
- `evaluate_incidents.py` 依赖 DB 里的 `incident_reports` 与每案 `map.json` 的 report/diagnosis 映射，
  重放时会复制 source DB 并清空旧 `events` / `sessions` / `incident_reports`，因此不会读到历史结果。
- Windows 上写文件要注意编码：PowerShell 5.1 的 `-Encoding utf8` 会带 BOM，会让 Python 报
  `SyntaxError: invalid non-printable character U+FEFF`；用 `UTF8Encoding($false)` 写。
- 仓库 `.gitattributes` 是 `* text=auto eol=lf`，脚本重定向产生的 CRLF 要归一。

## 7. 不再复现的部分

| 内容 | 现状 |
|---|---|
| 检测器训练与评测（Drain3 训练、TF-IDF+LR、Isolation Forest、LSTM 对照） | 随 `src/offline/detection/` 一起删除 |
| AUC / PR 曲线 / 阈值曲线 / `select_threshold(max_fpr=0.01)` | 随 `ops/scripts/evaluate_detector.py`、`report.py` 删除，不可复现 |
| 服务侧 LR 分数与 `threshold 4.048591446044616` | 服务检测器改为规则门禁 `RuleDetector`（阈值 0.6、≥1 行、分数在 [0,1] 无校准含义） |
| `artifacts/releases/v1.0_service` 模型包 | 不再需要；`platform verify` 只校验规则体与脱敏规则哈希 |

需要强调的是：**这两层互不替代**。132 例的 lab 重放走的是案例侧门禁 `src/offline/case/novelty.py`
（模板新颖度，拟合于正常窗口），与服务批处理的 `RuleDetector`（日志级别 + 关键词）是不同代码路径；
前者是本文验证的对象，后者只决定上传批次里哪些会话算异常。

## 8. 本次验证记录

| 项 | 值 |
|---|---|
| 分支 / 提交 | `v2` / `6820429` `refactor(v1): 移除研究训练轨，在线检测改为规则门禁` |
| 运行时间 | 2026-11-21 |
| 机器 | Windows，Python 3.11.16（uv），CPU 单机 |
| 重放产物 | `runtime/repro/`（gitignored，不提交） |
| 结论 | 132 例全在；事件切分、门禁理由/分数、案例 Top-1 与删除前基线逐条一致（差异 0） |
