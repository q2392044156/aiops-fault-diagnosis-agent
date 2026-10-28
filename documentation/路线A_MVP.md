# 路线 A MVP：本机 HDFS 故障实验台

> 目标：把"注入故障"变成一条符合项目自身协议的 `incident` 记录，让 Top-1 / MTTD 从 `N/A` 变成可计算的数字。
> 本期范围：本机 Docker Compose（1 NN + 3 DN）、3 个故障族、离线/真实两种模式、指标计算脚本。

---

## 1. 架构

```text
docker compose（1 NameNode + 3 DataNode）
        │  注入：dd / docker kill / hdfs dfsadmin
        ▼
harness/run_case.py
        │  t0 → 注入 → 等信号 → 观测窗 → cutoff
        │  采集日志 + docker stats → 脱敏 → sha256
        ▼
incident.json（五时间戳 + 证据引用 + 根因码）
        │  python -m aiops_diag.data incident import
        ▼
incident_registry ──┐
                    ├─ evaluate_incidents.py → Top-1 / Top-3 / MRR / MTTD
incident_reports ───┘（通过 map.json 关联）
```

## 2. 故障矩阵

| 故障族 | 注入方式 | 观测信号 | 恢复 |
| --- | --- | --- | --- |
| `DN_VOLUME` | dn1（tmpfs 128MB）`dd` 填满 | `No space left on device` / `Volume ... failed` | 删除 fill 文件 |
| `DN_HEARTBEAT` | `docker kill` dn2 | `Lost DataNode` / heartbeat | `docker start` |
| `NN_SAFE_MODE` | `hdfs dfsadmin -safemode enter` | `Safe mode is ON` | `-safemode leave` |

## 3. 五个时间戳与快照

| 时间戳 | 采集方式 | 本期状态 |
| --- | --- | --- |
| `fault_start` | 注入命令执行前 | ✅ |
| `first_observable_signal` | 轮询容器日志匹配信号正则 | ✅ |
| `agent_detected` | 平台写入 `events.detected_at` | ❌ 尚未接入，MTTD 返回 N/A |
| `human_confirmed` | 恢复后由复核人确认 | ✅（MVP 用固定复核人） |
| `recovered` | 恢复命令完成 + 集群健康 | ✅ |

**快照截止**：日志和指标只采集到 `cutoff = fault_start + observe`；恢复动作在 cutoff 之后，保证"诊断时看不到恢复后的数据"。

## 4. 实测：一次真实的 NameNode 安全模式故障

2026-10-28 在本机 Docker 上实际跑通：

| 项 | 值 |
| --- | --- |
| 集群 | 1 NameNode + 3 DataNode（3 个 Live datanodes） |
| 故障 | `hdfs dfsadmin -safemode enter` |
| fault_start | 11:02:17.265 |
| first_observable_signal | 11:02:18.958（**+1.69s**） |
| 观测窗 | 25s |
| 日志证据 | 570 字节，包含 `STATE* Safe mode is ON`，IP 已替换为 `<:IP:>` |
| 指标证据 | 4 条 `docker stats` 采样（CPU / 内存） |
| 记录校验 | `incident validate` 通过，`root_cause_metrics=AVAILABLE` |
| 入库 | `incident import` 成功，`status=ACTIVE` |

另外用 `--dry-run` 生成 `DN_VOLUME` 与 `DN_HEARTBEAT` 两条同形样本，用于无集群时的联调。

## 5. 接入诊断后的指标

`ingest.py` 把证据日志转换成平台日志行，创建批次/事件，并跑一次模板诊断，回填 `map.json`：

```text
事件数 3 | 可计入根因指标 3 | 有诊断报告 3
Top-1 0.6667 | Top-3 1.0 | MRR 0.8333 | MTTD N/A
排除原因 {}
```

| 事件 | 期望组件 | 名次 |
| --- | --- | --- |
| DN_VOLUME（dry-run） | DataNode | 1 |
| DN_HEARTBEAT（dry-run） | DataNode | 1 |
| NN_SAFE_MODE（真实集群） | NameNode | 2 |

两个 DataNode 故障命中第一；NameNode 安全模式排第二——因为日志里同时包含 DataNode 行，检索按关键词排序时把 DataNode 卡片排到了前面。这是**检索排序问题，不是标签问题**，也是下一步最值得改的地方（按组件过滤检索）。

MTTD 仍为 `N/A`：`agent_detected` 在生成 incident 时还没有（先写记录、后接入诊断，存在先后依赖）。下一步应把 ingest 提前到写 incident 之前。

## 6. 命令

```powershell
docker compose -f ops/lab/compose.yaml up -d
python ops/lab/harness/run_case.py --fault NN_SAFE_MODE --observe 25 --import-db runtime/lab/mvp.sqlite3
python ops/lab/harness/ingest.py --case ops/lab/cases/<incident_id> --database runtime/lab/mvp.sqlite3
python ops/scripts/evaluate_incidents.py --database runtime/lab/mvp.sqlite3 --cases ops/lab/cases
docker compose -f ops/lab/compose.yaml down -v
```

## 7. 局限与下一步

- **接入是后置的**：`ingest.py` 已能回填 `batch/event/diagnosis/report`，但它在 incident 写完之后才运行，导致 `agent_detected` 没能写进记录；
- **MTTD 仍为 N/A**：需要把 ingest 前移到写 incident 之前，或在接入后重写记录；
- **根因指标是组件级**：`DN_VOLUME` → `DataNode`，还没有代码级映射；
- 只覆盖 3 个故障族、单机、单次运行；距离 20 例 / 3 族的 MVP 目标还差批量编排与自动诊断。

下一步优先级：

1. 把 ingest 前移到 incident 生成之前，让 `agent_detected` 落进记录（MTTD 才能真正可算）；
2. 批量跑 20 例（每族 ≥6），冻结 20% 作为测试；
3. 给知识卡加 `root_cause_codes`，把指标升级到代码级。
