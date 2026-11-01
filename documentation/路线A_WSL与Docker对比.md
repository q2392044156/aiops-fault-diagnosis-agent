# 路线 A：WSL 与 Docker 两套实验台对比

> 目的：把"能测出真实故障"的 WSL 结果与"规模化但受环境限制"的 Docker 结果分开汇报，避免混在一起误读。

## 1. 数字对照

| 项 | WSL 单机（Hadoop 3.3.6） | Docker Compose（1NN+3DN） |
| --- | --- | --- |
| 故障族 | 卷故障（ro remount）、心跳丢失（kill） | 卷满（dd）、心跳（kill）、安全模式 |
| 样本 | **68**（38 卷 + 10 心跳 + 20 安全模式） | **81**（28 卷 + 27 心跳 + 26 安全模式） |
| Top-1 | **100%**（CI [0.9465, 1.0]） | 91.4%（CI [0.8322, 0.9575]） |
| Top-3 | 100% | 93.8% |
| Top-5 | 100% | 93.8% |
| MRR | 1.00 | 0.9218 |
| 冻结测试集 | n=14，Top-1 100% | n=30，Top-1 90.0%（CI [0.74, 0.97]） |
| 分族 | 卷 38/38、心跳 10/10、安全模式 20/20 | 卷 21/28、心跳 27/27、安全模式 26/26 |

## 2. 为什么差距这么大

1. **注入保真度**
   - WSL 卷故障是**真实卷失败**：`mount -o ro` 后 DataNode 启动即报 `DiskErrorException: Too many failed volumes`，证据链完整；
   - Docker 卷满 28 例归因：21 例命中、2 例排序、5 例证据缺失；`dd` 填盘让少数案例拿不到 ENOSPC，主因已从排序转为证据。
2. **心跳可观测性**
   - WSL 把 `dfs.heartbeat.interval=2`、`recheck-interval=2000` 写进配置，约 20–25 秒就能看到 `removeDeadDatanode`；
   - Docker 固定窗口内经常等不到该日志。
3. **单机 vs 多机**
   - WSL 只有 1 个 DataNode，写入必然落到它身上；Docker 3 个 DN 时写入随机分布，卷满很难命中目标节点。

## 3. 两套结果怎么用

- **WSL 29 例**：证明"这类故障可以造出来、也能被诊断链路命中"，适合放在简历/面试里讲方法与证据；
- **Docker 81 例**：证明"规模化跑通过、并暴露了环境边界"，适合讲工程取舍与失败分析；
- 两者**不能相加**，注入形态、集群规模、样本量都不同。

## 4. 边界

- WSL 仍是单机、单一注入形态（卷=只读 remount、心跳=kill），没有覆盖"写满/慢盘/网络抖动"；
- 48 例的 Top-1 100% 不代表通用准确率，CI 下限 0.926；ENOSPC 形态仍未打通；
- Docker 的 81 例仍是历史记录，环境限制未解除。

## 5. 结论与范围（2026-10-29 定稿）

> Docker 侧的 `NN_AVAILABILITY` 扩展尝试未通过（证据采集需重做），暂不纳入；WSL 已新增 `NN_SAFE_MODE` 20 例。

- **保留**：卷故障 = 只读 remount；心跳 = kill + 2s 心跳；
- **不做**：真实 ENOSPC、IO error 注入；
- **原因**：
  - ENOSPC 被 NameNode 容量预检挡住，写请求到不了 DN；
  - WSL 的 device-mapper 只提供 `verity / striped / linear / error`，**没有 `flakey`**，无法做 `error_writes` 形态；
- 因此 48 例（38 卷 + 10 心跳）的 **Top-1 100%** 是"只读卷故障 + 心跳丢失"这一范围的结论，不外推到写满/慢盘/网络故障。

## 6. 冻结切分格式

两套实验台使用同一个 JSON schema，评测脚本按 `--split-file` 读取；未显式指定且 cases 目录含 `wsl_cases` 时自动使用 WSL 切分。

```json
{"note": "...", "fraction": 0.2, "total": 29, "test": ["inc_...", "..."]}
```

| 文件 | 用途 |
| --- | --- |
| `resources/evaluation/lab/frozen_split.json` | Docker 81 例的 30 例测试集 |
| `resources/evaluation/lab/wsl_split.json` | WSL 29 例的 6 例测试集 |

## 7. 复现

```bash
python ops/lab/wsl/run_case.py --fault DN_VOLUME --database runtime/lab/wsl.sqlite3
python ops/lab/wsl/run_case.py --fault DN_HEARTBEAT --database runtime/lab/wsl.sqlite3
python ops/scripts/evaluate_incidents.py --database runtime/lab/wsl.sqlite3 \
  --cases ops/lab/wsl_cases --split-file resources/evaluation/lab/wsl_split.json \
  --output resources/evaluation/lab/wsl
```
