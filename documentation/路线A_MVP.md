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

## 5. 真实集群 41 例与代码级指标

2026-10-28 在本机 Docker 集群真实跑完 41 例（14 卷满 + 14 心跳丢失 + 13 安全模式），全部接入诊断并回填代码级根因码：

| 指标 | 值 |
| --- | --- |
| 事件数 | 41 |
| Top-1 | **0.8537** |
| Top-3 | **1.00** |
| MRR | **0.9024** |
| Top-1 95% CI | [0.7156, 0.9312] |
| 冻结测试集（20%，n=7） | Top-1 0.8571，CI [0.4869, 0.9743] |
| MTTD | 40.0s |

按族拆开：

| 故障族 | n | Top-1 |
| --- | --- | --- |
| DN_VOLUME | 14 | 0.571 |
| DN_HEARTBEAT | 14 | 1.0 |
| NN_SAFE_MODE | 13 | 1.0 |

读法：

- **心跳 0 → 1.0**：观测窗按故障族自适应（心跳 40s），NameNode 打出 `removeDeadDatanode` 后检索才有信号词；
- **安全模式 0.69 → 1.0**：去掉"安全/模式"的中文同义词加权，避免 `NN_AVAILABILITY` 被顶到第一；
- **卷满仍 0.571**：日志里 volume/disk/heartbeat 词重叠，`DN_HEARTBEAT` 卡会排到前面；两张卷卡共享 `DN_VOLUME` 的问题已消除，但排序仍不稳；
- 测试集按 `incident_id` 的 SHA-256 稳定划分 20%，n=7，Top-1 0.857，区间很宽。

MTTD 40.0s = 心跳族 40 秒观测窗 + 接入与诊断耗时，属于**上限**。

## 6. 命令

```powershell
docker compose -f ops/lab/compose.yaml up -d
python ops/lab/harness/run_case.py --fault NN_SAFE_MODE --observe 25 --import-db runtime/lab/mvp.sqlite3
python ops/lab/harness/ingest.py --case ops/lab/cases/<incident_id> --database runtime/lab/mvp.sqlite3
python ops/scripts/evaluate_incidents.py --database runtime/lab/mvp.sqlite3 --cases ops/lab/cases
docker compose -f ops/lab/compose.yaml down -v
```

## 7. 局限与下一步

- **卷满检索仍不稳**：`DN_HEARTBEAT` 卡与卷卡共享 volume/disk/datanode 词，6 例排到 2–3 名；
- **MTTD 含观测窗**：40 秒主要来自心跳族刻意等待；
- **测试集太小**：n=7，置信区间 [0.49, 0.97]，还不足以对外声称泛化；
- 单机、单次运行、41 例；所有数字来自同一台机器。

下一步优先级：

1. **候选消歧**：同组件内按根因码互斥排序，解决卷满与心跳的词重叠；
2. **卷满注入加写入负载**：持续写块，让 `No space left on device` 成为主信号；
3. n 扩到 80+，固定测试集，再报一次带区间的数字。
