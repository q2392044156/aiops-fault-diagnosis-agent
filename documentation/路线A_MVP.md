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
| Top-1（严格代码级） | **0.5062** |
| Top-3 | **0.7654** |
| MRR | **0.6255** |
| Top-1 95% CI | [0.3995, 0.6123] |
| 冻结测试集（n=17） | Top-1 0.5294，CI [0.3096, 0.7384] |
| MTTD | 46.6s |

按族拆开：

| 故障族 | n | Top-1 |
| --- | --- | --- |
| DN_VOLUME | 28 | 0.036 |
| DN_HEARTBEAT | 27 | 0.519 |
| NN_SAFE_MODE | 26 | 1.0 |

本轮把"信号码硬过滤"接进检索（命中 `no space` / `lost heartbeat` 就只召回对应码的卡片），效果是 **Top-3 0.60 → 0.77、MRR 0.54 → 0.63**，但 **Top-1 未变**：正确码进了候选，卷满仍缺 ENOSPC 主信号。

**口径说明（关键）**：这一版把"代码缺失时回退到组件匹配"去掉了——只要报告里出现了根因码，就必须码对才算命中。上一轮 0.85 是**组件级**口径，包含了大量"码不对但组件对"的情况，不能当作代码级成绩。

读法：

- **安全模式 26/26**：`Safe mode is ON` 稳定出现在日志，检索直接命中 `NN_SAFE_MODE`；
- **心跳 0.519**：观测窗拉到 40s 后有信号，但仍有约一半案例检索把 `DN_VOLUME` 或 `BLOCK_REPORT` 排在前面；
- **卷满 0.036**：写负载没有在窗口内制造出 ENOSPC 日志，`DN_VOLUME` 卡基本没被召回——这是证据问题，不是排序问题。

MTTD 46.6s = 心跳族 40 秒观测窗 + 接入与诊断耗时，属于**上限**。## 6. 命令

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
- **测试集仍小**：n=17，CI [0.31, 0.74]；
- 单机、单次运行、81 例；所有数字来自同一台机器。

下一步优先级：

1. **修卷满证据**：先启动写负载再填盘，或直接写大文件触发 `DiskOutOfSpaceException`；
2. **提升召回**：对"信号码"做硬过滤（命中 `no space` 就只召回 `DN_VOLUME` 卡），而不是只做重排；
3. 把冻结测试集扩到 30+，再报一次区间。
