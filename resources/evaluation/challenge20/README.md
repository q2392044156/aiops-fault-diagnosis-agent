# challenge20：受控分布偏移挑战集

## 目的

统一 4 类测试集的案例多数投票是 60/60，但它和训练集来自同一批注入脚本、同一时间窗、同一套日志模板。为了回答“换格式、换时间、换主机名、换故障表述后还认不认得”，本目录构造 20 个**未参与 unified4 训练/测试**的独立 holdout 案例，并对它们施加可控扰动。

这不是新的自然采集数据，也不是生产分布样本。它是一组“有明确变换轴”的压力测试，用来暴露规则/模板链路的脆弱点。

## 数据来源

- 来源：ops/lab/cases 中 20 个早期自然案例，均未进入 unified4 manifest。
- 类别：卷故障 7、心跳丢失 7、安全模式 6；没有网络分区。
- 原始日志：每例约 12 行，包含正常 workload 与 1 条 WARN/ERROR 故障信号。
- 标签：沿用原始 incident 的 root_cause_code；不重新标注。

源案例与 unified4 的交集检查见 tests/test_challenge20.py。

## 四个变换组（每组 5 例）

| 组 | 变换 | 目的 |
| --- | --- | --- |
| format_time | Docker 文本重渲染为 WSL 行格式；时间整体 -30 天；主机名改为生产风格；同步重写 incident/metrics/hash | 跨格式、跨时间、跨主机命名 |
| evidence_drop | 在 format_time 基础上删除正常 INFO，只保留 WARN/ERROR 与故障行 | 低证据、短窗口 |
| paraphrase | 在 format_time 基础上同义改写故障表述，移除原始关键词 | 未见表述的语义偏移 |
| paraphrase_distractor | 在 paraphrase 基础上，在故障前插入另一类故障的已知信号 | 语义偏移 + 干扰信号优先级 |

同义改写示例：

| 原始 | 挑战集 |
| --- | --- |
| `Lost DataNode datanode2` | `DataNode prod-datanode-08 missed its liveness deadline` |
| `Volume /data/1 failed, 0 bytes available` | `Storage volume /data/1 is full (0 bytes free)` |
| `No space left on device` | `ENOSPC while allocating a new block` |
| `Entering safe mode` | `Entering maintenance mode` |
| `Safe mode is ON.` | `Startup guard is active.` |

改写后的日志不再包含当前 `CODE_SIGNALS` 的原始关键词；干扰组例外，因为它故意插入另一类故障的原始信号。

## 评测协议

1. 用 WSL 检测器 `artifacts/detectors/wsl_sliding_v4.json` 和 WSL 模板做门禁；60s/10s 滑窗，500 行上限。
2. 每个 PASS 窗口生成一个 event，逐 event 走在线 7 节点诊断；不重新训练检测器。
3. 案例级同时报告四种口径：
   - 多数投票：案例内所有 event 的首选根因取众数；
   - 首事件：时间上第一个 event 的首选根因；
   - 所有事件都对：案例内每个 event 都命中；
   - 任一 event：至少一个 event 命中。
4. 事件级报告 Top-1。
5. 所有报告都是 `DEGRADED_TEMPLATE`，指标反映规则/模板链路，不是 LLM 生成质量。

## 结果（2026-11-16）

门禁 20/20 PASS，共 57 个 event。

| 指标 | 结果 | 95% Wilson CI |
| --- | --- | --- |
| 案例多数投票 | 13/20 = 65.00% | [43.29%, 81.88%] |
| 案例首事件 | 13/20 = 65.00% | [43.29%, 81.88%] |
| 案例所有事件都对 | 12/20 = 60.00% | [38.66%, 78.12%] |
| 案例任一 event | 13/20 = 65.00% | [43.29%, 81.88%] |
| 事件 Top-1 | 31/57 = 54.39% | [41.59%, 66.63%] |

按扰动组：

| 组 | 案例多数 | 所有事件都对 | 事件 Top-1 |
| --- | --- | --- | --- |
| format_time | 5/5 | 5/5 | 17/17 |
| evidence_drop | 5/5 | 5/5 | 5/5 |
| paraphrase | 2/5 | 2/5 | 6/15 |
| paraphrase_distractor | 1/5 | 0/5 | 3/20 |

按故障族：

| 故障族 | 案例多数 | 所有事件都对 | 事件 Top-1 |
| --- | --- | --- | --- |
| 卷故障 | 7/7 | 6/7 | 18/19 |
| 心跳丢失 | 3/7 | 3/7 | 7/21 |
| 安全模式 | 3/6 | 3/6 | 6/17 |

## 结果说明

- 只换格式/时间/主机名（format_time）和删正常行（evidence_drop）没有破坏诊断，说明这几条工程链路是稳的。
- 同义改写开始破坏：心跳类的 `missed its liveness deadline` / `schedule replication` 不再命中 `CODE_SIGNALS` 的 `lost heartbeat`、`lost datanode` 等关键词，心跳 11/12 两个 paraphrase 案例都掉到 `DN_VOLUME`；安全模式 18 被知识卡排序带到 `BLOCK_REPLICATION`。paraphrase 组事件级只有 6/15。
- 叠加干扰信号后更差：`paraphrase_distractor` 只有 1/5 案例多数正确，事件级 3/20；最早窗口被前置的另一类故障信号主导，说明当前规则没有“故障时间/组件/信号强度”的优先级校准。
- 修正日志正文的内嵌时间后，安全模式 18 从正确变为 `BLOCK_REPLICATION`；本次只改了日期文本，未做单项消融，不能把差异单独归因于日期，但说明知识卡召回排序对与故障无关的文本也敏感。
- 卷故障改写仍全对，因为 `Storage volume ... full` 仍带有 volume/full 弱词；这反而说明当前链路对“词面”而不是“语义”敏感。
- 这是挑战集要暴露的问题，不是模型变差；同一批报告仍是确定性规则/模板链路。

## 复现

生成挑战案例（需要本地 ops/lab/cases，且这些源案例不提交 Git）：

    python ops/scripts/build_challenge20.py

重放门禁与逐 event 诊断（需要 unified4 的 WSL 源库和制品）：

    python ops/lab/harness/run_gate_batch.py ^
      --cases resources/evaluation/challenge20/cases ^
      --database runtime/challenge20/events_committed.sqlite3 ^
      --work runtime/challenge20/work_committed ^
      --output runtime/challenge20/incidents_committed.json ^
      --source-db runtime/unified4/wsl_source.sqlite3 ^
      --source-type wsl ^
      --detector artifacts/detectors/wsl_sliding_v4.json ^
      --detector-release novelty_wsl_sliding_v4 ^
      --template-dir artifacts/templates/wsl ^
      --gate-output resources/evaluation/challenge20/gates.json ^
      --window-seconds 60 --window-step 10 --max-rows 500

评测：

    python ops/scripts/evaluate_challenge20.py

## 文件

- `manifest.json`：20 例的 case_id、类别、扰动组、源案例、标签。
- `cases/`：20 个可重放的 incident + evidence + challenge 元数据。
- `gates.json`：门禁和 event/report 映射。
- `results.json`：案例/事件指标、分组指标、错误案例明细。
- 生成脚本：ops/scripts/build_challenge20.py。
- 评测脚本：ops/scripts/evaluate_challenge20.py。
- 测试：tests/test_challenge20.py。

## 边界

- 20 例是源 holdout 的**派生副本**，不是 20 个独立自然样本；不能把 65% 当作生产泛化率。
- 只有 3 类，没有网络分区；不能覆盖 4 类完整分布。
- 源日志很短（约 12 行），窗口只有 1–4 个，事件级指标波动大。
- 变换是确定性的、人工设计的，不是真实运维中自然发生的表述漂移。
- 57 份报告全部为 `DEGRADED_TEMPLATE`，没有验证 LLM 路径。
