# 离线演示：5 分钟看到完整链路

这个目录让任何人**不需要 GPU、不需要 API Key、不需要下载 186 MB 数据集**，就能在本地跑通一次真实的诊断：

    一条 HDFS 日志 → 解析脱敏 → 会话与异常检测 → 事件聚合 → 知识检索 → 受控 Agent → 带引用的报告 → 人工复核 → 审计留痕

全程约 1 秒，产出是一个真实写入 SQLite 的报告和一个真实的审批单。

## 30 秒跑起来

```powershell
conda activate aiops-fault-diagnosis-agent
python demo/run_demo.py
```

或者用 Make（需要 GNU Make；Windows 上直接用上面的 python 命令）：

```bash
make demo          # 文本输出
make demo-json     # 机器可读摘要（CI 用）
```

## 你会看到什么

```text
[1/7] 解析、脱敏与异常检测
  总行数 12 | 解析成功 10 | 隔离 2 | 会话 3 | 异常会话 1 | 事件 1
[2/7] 事件聚合
  evt_... | 会话数 1 | 最高分 2.00 (阈值 1.00)
[3/7] 受控诊断：每个节点完成后主动让出 worker
  节点完成 -> VALIDATED / DETECTED / EVIDENCE_COLLECTED / RETRIEVED / HYPOTHESES_RANKED / REPORT_VALIDATED
[4/7] 证据与候选原因
  工具调用 7 次 / 6 类：detect_anomaly, query_logs, retrieve_runbook, ...
  证据 7 条（日志 4 / 知识 3）
[5/7] 安全门禁
  引用合法: 通过 ；execution_allowed=false: 通过
[6/7] 报告正文
  # 事件诊断报告 ...
[7/7] 人工复核（签字 ≠ 执行）
  审批单 apr_... | 状态 PENDING | 绑定报告哈希 ...
  复核已提交：APPROVED
```

几个值得注意的细节：

| 现象 | 说明 |
| --- | --- |
| `隔离 2` | 一行格式错误、一行没有 block 编号，都被放进隔离区并记账，没有静默丢弃 |
| `节点完成 -> ...` 六次 | Agent 是确定性状态机，每完成一个节点主动让出 worker，便于公平调度与断点恢复 |
| `工具调用 7 次` | 全部是只读工具；预算上限是 8 次 |
| 低置信度 + 需复核 | 知识卡组件名与日志组件名不完全一致，系统保守地转人工，而不是硬给结论 |
| 签字 ≠ 执行 | 审批只改状态，系统里没有任何执行运维操作的入口 |

## 它是真的吗？

是，也不是，必须说清楚：

- **真的部分**：解析器、脱敏、会话切分、事件聚合、SQLite 落库、Agent 状态机、工具审计、证据引用校验、审批绑定与审计日志，**全部走生产代码路径**。
- **演示替代的部分**：异常检测用了一个 20 行的规则检测器（含 ERROR 即异常），替代训练好的 TF-IDF + 逻辑回归；知识检索用关键词打分替代 BM25 + BGE + RRF；没有配置 API Key 时报告走确定性模板降级。
- 换句话说：**管道是真的，模型是替身**。这样做的目的是让演示不依赖任何大文件或密钥，而不是为了美化结果。

真实链路请见仓库根目录的 [README](../README.md) 与 [v1.2 技术报告](../documentation/v1.2_RC1_实施报告.md)。

## 3 分钟演示脚本（面试可直接用）

1. **0:00–0:30** 打开终端，运行 `python demo/run_demo.py`，说一句："这是一个离线可复现的端到端演示，不需要 Key。"
2. **0:30–1:00** 指着 `[1/7]`："12 行日志里有 2 行被隔离——一行格式坏、一行没有 block 号；我们从不静默丢数据。"
3. **1:00–1:40** 指着 `[3/7]` 的节点列表："Agent 不是让大模型自由发挥，而是 7 个固定节点，每个节点完成后让出 worker，崩溃可续跑。"
4. **1:40–2:20** 打开 `demo/.runtime/service.sqlite3`，展示 `agent_tool_calls` 与 `agent_audit_records`："每次工具调用、每个审批动作都有审计行。"
5. **2:20–3:00** 指着 `[5/7]`："引用必须命中本次证据，建议的 `execution_allowed` 恒为 false；审批只是'人看过'，不是执行。"

## 文件结构

```text
demo/
├─ run_demo.py                  # 演示入口（约 350 行，含注释）
├─ fixtures/
│  ├─ hdfs_demo.log             # 12 行脱敏前的 HDFS 日志
│  └─ knowledge/*.json          # 3 张知识卡（磁盘满 / 安全模式 / 写管道）
└─ .runtime/                    # 运行产物（已 gitignore）：SQLite、Parquet、报告
```

## 常见问题

**Q：为什么报告状态是 DEGRADED_TEMPLATE？**
A：离线演示没有配置 API Key，按设计降级为确定性模板。设置 `DEEPSEEK_API_KEY` 并走真实 `service_v12_rc1.yaml` 配置时，才会调用模型生成 EVIDENCE_SUPPORTED 报告。

**Q：能改成真实模型吗？**
A：可以，但需要先构建发布制品（模型、知识库、Agent 发布清单）。演示刻意不依赖它们，否则"5 分钟上手"就不成立。

**Q：demo/.runtime 可以删吗？**
A：可以，每次运行都会重建。
