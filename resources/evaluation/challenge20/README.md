# challenge20：受控分布偏移回归集

## 目的

统一 4 类测试集的案例多数投票是 60/60，但它和训练集来自同一批注入脚本、同一时间窗、同一套日志模板。为了回答“换格式、换时间、换主机名、换故障表述后还认不认得”，本目录构造 20 个未参与 unified4 训练/测试的派生案例，并对它们施加可控扰动。

这不是新的自然采集数据，也不是生产分布样本。它是一组“有明确变换轴”的压力测试，用来暴露规则/模板链路的脆弱点。

> 注意：这 20 例最初是 holdout，但本轮信号本体改进参考了它们的失败案例。因此它现在是**回归集**，不再是盲测集；20/20 只说明已知问题已修复，不能作为跨分布泛化率。

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

改写后的日志不再包含旧关键词表里的原始表述；干扰组例外，因为它故意插入另一类故障的原始信号。

## 评测协议

1. 用 WSL 检测器 `artifacts/detectors/wsl_sliding_v4.json` 和 WSL 模板做门禁；60s/10s 滑窗，500 行上限。
2. 同一案例、同一组件、时间重叠或相接的 PASS 窗口合并为一个 event，再逐 event 走在线 7 节点诊断；不重新训练检测器。
3. 案例级同时报告四种口径：
   - 多数投票：案例内所有 event 的首选根因取众数；
   - 首事件：时间上第一个 event 的首选根因；
   - 所有事件都对：案例内每个 event 都命中；
   - 任一 event：至少一个 event 命中。
4. 事件级报告 Top-1。
5. 所有报告都是 `DEGRADED_TEMPLATE`，指标反映规则/模板链路，不是 LLM 生成质量。

## 结果（2026-11-16，改进后）

门禁 20/20 PASS，合并后共 21 个 event。

| 指标 | 初版（未改规则） | 当前 | 95% Wilson CI |
| --- | --- | --- | --- |
| 案例多数投票 | 13/20 = 65.00% | 20/20 = 100% | [83.89%, 100%] |
| 案例首事件 | 13/20 = 65.00% | 20/20 = 100% | [83.89%, 100%] |
| 案例所有事件都对 | 12/20 = 60.00% | 20/20 = 100% | [83.89%, 100%] |
| 案例任一 event | 13/20 = 65.00% | 20/20 = 100% | [83.89%, 100%] |
| 事件 Top-1 | 31/57 = 54.39% | 21/21 = 100% | [84.54%, 100%] |
| 报告模式 | 57/57 DEGRADED | 21/21 DEGRADED | — |

按扰动组：

| 组 | 案例多数 | 所有事件都对 | 事件 Top-1 |
| --- | --- | --- | --- |
| format_time | 5/5 | 5/5 | 5/5 |
| evidence_drop | 5/5 | 5/5 | 5/5 |
| paraphrase | 5/5 | 5/5 | 5/5 |
| paraphrase_distractor | 5/5 | 5/5 | 6/6 |

按故障族：

| 故障族 | 案例多数 | 所有事件都对 | 事件 Top-1 |
| --- | --- | --- | --- |
| 卷故障 | 7/7 | 7/7 | 8/8 |
| 心跳丢失 | 7/7 | 7/7 | 7/7 |
| 安全模式 | 6/6 | 6/6 | 6/6 |

## 改进内容

- 新增可解释信号本体 `src/online/diagnosis/signals.py`：每个根因码登记正则、权重和角色（direct / context / support），按日志级别加权，取最高分根因，不再用固定根因优先级覆盖。
- 心跳：`missed its liveness deadline` 2.3、`lost heartbeat` 2.2、`lost/dead/stale datanode` 1.9。
- 卷：`no space left` / `ENOSPC` 2.3、`failed volumes` 2.3、`volume ... failed/full` 1.4。
- 安全模式：`safe mode` 2.3、`startup guard` 2.2、`reported blocks ... threshold` 1.0（context）。
- 干扰信号：`BLOCK* ... replicat` 只算 0.4 support，不再压过真正的 direct 信号。
- 证据选择、`rank_root_causes`、`detected_codes_from_text` 和 `v11` 共用同一套信号本体。
- 相接窗口合并：同一案例/组件、时间重叠或间隔为 0 的 PASS 窗口合并，57 个 event 降为 21 个，避免同一段故障重复诊断。
- 修复 `_signature` 的数字正则（原 `r"\\d+"` 实际匹配反斜杠），`normal workload line 0-9` 现在会归一化去重。

## 结果说明

- 初版失败集中在词面敏感：心跳同义表述不命中、卷故障被 “lost datanode” 干扰、安全模式被知识卡排序带走。
- 当前规则已覆盖这些已知表述和干扰组合，所以回归集全部通过。
- **这是对已见案例的修复，不是对未见分布的泛化证明。** 20 例的失败模式参与了规则设计，100% 不能与统一测试集的 100% 等价看待。
- 下一步应另建未参与调参的 challenge21，或重新采集真实偏移样本，再报告一次盲测结果。

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
      --window-seconds 60 --window-step 10 --max-rows 500 ^
      --skip-incident-eval

默认开启事件合并；加 `--no-event-merge` 可复现初版的逐窗口事件口径。

`--skip-incident-eval` 只跳过基于源库 `incident_registry` 的旧摘要；挑战集指标以 `evaluate_challenge20.py` 为准。

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

- 20 例是源 holdout 的**派生副本**，不是 20 个独立自然样本；且已参与本轮调参，不能把 100% 当作生产泛化率。
- 只有 3 类，没有网络分区；不能覆盖 4 类完整分布。
- 源日志很短（约 12 行），窗口只有 1–4 个，事件级指标波动大。
- 变换是确定性的、人工设计的，不是真实运维中自然发生的表述漂移。
- 21 份报告全部为 `DEGRADED_TEMPLATE`，没有验证 LLM 路径。
