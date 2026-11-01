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

## 5. 真实集群 81 例（严格代码级口径）

2026-10-28 在本机 Docker 集群真实跑完 81 例（28 卷满 + 27 心跳丢失 + 26 安全模式），全部接入诊断：

| 指标 | 值 |
| --- | --- |
| 事件数 | 81 |
| Top-1（严格代码级） | **0.9136** |
| Top-3 | **0.9383** |
| Top-5 | **0.9383** |
| MRR | **0.9218** |
| Top-1 95% CI | [0.8322, 0.9575] |
| 冻结测试集（n=30） | Top-1 0.9000，CI [0.7438, 0.9654] |
| MTTD | 46.6s |

按族拆开：

| 故障族 | n | Top-1 |
| --- | --- | --- |
| DN_VOLUME | 28 | 0.75 |
| DN_HEARTBEAT | 27 | 1.0 |
| NN_SAFE_MODE | 26 | 1.0 |

P0 修复了"信号行被截断"（心跳 14/27 → 27/27）；P1 增加"无强信号时的弱先验重排"，卷满 6/28 → 21/28，总体 Top-1 从 56.8% 升到 **91.4%**。

**口径说明（关键）**：这一版把"代码缺失时回退到组件匹配"去掉了——只要报告里出现了根因码，就必须码对才算命中。上一轮 0.85 是**组件级**口径，包含了大量"码不对但组件对"的情况，不能当作代码级成绩。

读法：

- **安全模式 26/26**：`Safe mode is ON` 稳定出现在日志，检索直接命中 `NN_SAFE_MODE`；
- **心跳 27/27**：`removeDeadDatanode` 行进入证据后，检索稳定命中 `DN_HEARTBEAT`；
- **卷满 21/28**：5 例没有 ENOSPC 证据，2 例仍排第 2。

本轮还试了两件事，都没有把数字拉起来：

- **卷满注入换面（第 4 次）**：停掉 dn2/dn3、客户端用 `-Ddfs.replication=1`、写 16MB 块，试图让 dn1 真正返回 ENOSPC；结果 DN 仍然没有卷失败日志，已回滚到稳定配置。
- **心跳自适应窗口**：从固定 40s 改成"等到信号 + 5s，最多 90s"；6 例探针 Top-1 0.33（CI 很宽），没有改善——失败案例的根本原因是 90s 内 NameNode 仍未打出可用信号。

MTTD 46.6s 含心跳族观测窗与接入耗时，属于**上限**。

## 5.1 环境边界实测（2026-10-29）

为绕开 root + tmpfs 的限制，本轮把 dn1 改为 **uid 1000 + 64MB tmpfs**（DataNode 能正常注册），并尝试用 HDFS 写入把卷写满：

- `hdfs dfs -put` 写第 7 个 8MB 块时报 `0 of the 1 minReplication nodes`，dn1 随后被排除；
- 但 dn1 日志里**没有** `No space` / `DiskOutOfSpaceException`，`df` 显示数据目录只用了 16K；
- 说明写入并未真正落到 dn1 的 tmpfs，卷满证据链依然不可得。

心跳族把窗口改为"信号 +5s、最多 90s"，6 例探针 Top-1 0.33，没有改善——90s 内 NameNode 仍经常没有 `removeDeadDatanode`。

**结论（已更新）**：Docker Desktop 下卷满与心跳仍不可复现；但 **WSL 单机 Hadoop 3.3.6 + 64MB loop** 已能稳定注入卷故障（只读 remount），WSL 已跑 **68 例**（38 卷 + 10 心跳 + 20 安全模式），Top-1 **98.5%**、CI [0.9213, 0.9974]，见 [wsl/](../ops/lab/wsl/README.md)。

## 6. 命令

```powershell
docker compose -f ops/lab/compose.yaml up -d
python ops/lab/harness/run_case.py --fault NN_SAFE_MODE --observe 25 --import-db runtime/lab/mvp.sqlite3
python ops/lab/harness/ingest.py --case ops/lab/cases/<incident_id> --database runtime/lab/mvp.sqlite3
python ops/scripts/evaluate_incidents.py --database runtime/lab/mvp.sqlite3 --cases ops/lab/cases
docker compose -f ops/lab/compose.yaml down -v
```

## 7. 局限与下一步

- **卷满证据缺失**：`dd` 填满 tmpfs 后写负载没产生 ENOSPC 日志，卷卡召回率接近 0；
- **检索召回不稳**：心跳族一半案例把非目标码排在前面；
- **测试集仍偏小**：n=30，CI [0.30, 0.64]；
- 单机、单次运行、81 例；所有数字来自同一台机器。

下一步优先级：

1. **卷满换环境**：Linux 主机 + loop 设备，或非容器化 DataNode，先验证 ENOSPC 再谈指标；
2. **心跳换采集**：`docker logs -f` 流式 + 更长等待，先保证信号出现；
3. **对外只报稳定链路**：安全模式 26/26 + 明确标注"卷满/心跳环境不支持"，把 81 例总表作为工程记录而非效果承诺。
