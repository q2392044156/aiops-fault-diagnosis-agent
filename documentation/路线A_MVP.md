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

## 5. 真实集群 20 例与代码级指标

2026-10-28 在本机 Docker 集群真实跑完 20 例（7 卷满 + 7 心跳丢失 + 6 安全模式），全部接入诊断并回填代码级根因码：

| 指标 | 值 |
| --- | --- |
| 事件数 | 20 |
| Top-1 | **0.50** |
| Top-3 | **1.00** |
| MRR | **0.6917** |
| MTTD | **26.8s** |

按族拆开：

| 故障族 | n | Top-1 | MRR |
| --- | --- | --- | --- |
| DN_VOLUME | 7 | 0.571 | 0.786 |
| DN_HEARTBEAT | 7 | 0.0 | 0.333 |
| NN_SAFE_MODE | 6 | 1.0 | 1.0 |

读法：

- **安全模式 6/6**：`Safe mode is ON` 直接出现在日志里，检索能命中 `NN_SAFE_MODE`；
- **卷满 4/7**：命中时是代码级 `DN_VOLUME`，未命中时仍能命中组件（Top-3 = 1.0）；
- **心跳 0/7**：15 秒窗口内 NameNode 还没打印 dead datanode，检索拿不到信号词，只能按组件召回，全部排第 3。

MTTD 26.8s = 15 秒观测窗 + 接入与诊断耗时，所以它是**上限**；改成流式接入后会更低。

## 6. 命令

```powershell
docker compose -f ops/lab/compose.yaml up -d
python ops/lab/harness/run_case.py --fault NN_SAFE_MODE --observe 25 --import-db runtime/lab/mvp.sqlite3
python ops/lab/harness/ingest.py --case ops/lab/cases/<incident_id> --database runtime/lab/mvp.sqlite3
python ops/scripts/evaluate_incidents.py --database runtime/lab/mvp.sqlite3 --cases ops/lab/cases
docker compose -f ops/lab/compose.yaml down -v
```

## 7. 局限与下一步

- **心跳族需要更长窗口**：15 秒内 NameNode 未打印 dead datanode，心跳 0/7 是窗口问题，不是映射问题；
- **卷满检索不稳**：`volume-failure` 与 `disk-full` 两张卡都可能命中 `DN_VOLUME`，排序在 1/2 之间摆动；
- **MTTD 含观测窗**：26.8 秒里有 15 秒是刻意等待；
- 单机、单次运行、20 例；还没有冻结测试集与置信区间。

下一步优先级：

1. 心跳案例把观测窗拉到 60s 或改流式，先拿到 dead datanode 信号；
2. 合并 `volume-failure` / `disk-full` 的 `DN_VOLUME` 卡片，消除排序抖动；
3. 冻结 20% 作为测试集，把 n 扩到 40+ 再报置信区间。
