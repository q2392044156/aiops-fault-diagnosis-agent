# 路线 A：WSL 与 Docker 两套实验台对比

> 目的：把"能测出真实故障"的 WSL 结果与"规模化但受环境限制"的 Docker 结果分开汇报，避免混在一起误读。

## 1. 数字对照

| 项 | WSL 单机（Hadoop 3.3.6） | Docker Compose（1NN+3DN） |
| --- | --- | --- |
| 故障族 | 卷故障（ro remount）、心跳丢失（kill） | 卷满（dd）、心跳（kill）、安全模式 |
| 样本 | **29**（19 卷 + 10 心跳） | **81**（28 卷 + 27 心跳 + 26 安全模式） |
| Top-1 | **100%**（CI [0.883, 1.0]） | 50.6%（CI [0.40, 0.61]） |
| Top-3 | 100% | 76.5% |
| MRR | 1.00 | 0.63 |
| 冻结测试集 | n=6，Top-1 100%（CI [0.61, 1.0]） | n=30，Top-1 46.7%（CI [0.30, 0.64]） |
| 分族 | 卷 19/19、心跳 10/10 | 卷 1/28、心跳 14/27、安全模式 26/26 |

## 2. 为什么差距这么大

1. **注入保真度**
   - WSL 卷故障是**真实卷失败**：`mount -o ro` 后 DataNode 启动即报 `DiskErrorException: Too many failed volumes`，证据链完整；
   - Docker 卷满靠 `dd` 填 tmpfs，NameNode 常常先拒绝分配，DN 收不到写请求，日志里没有 ENOSPC。
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
- 29 例的 Top-1 100% 不代表通用准确率，CI 下限 0.883，测试集只有 6 例；
- Docker 的 81 例仍是历史记录，环境限制未解除。

## 5. 复现

```bash
python ops/lab/wsl/run_case.py --fault DN_VOLUME --database runtime/lab/wsl.sqlite3
python ops/lab/wsl/run_case.py --fault DN_HEARTBEAT --database runtime/lab/wsl.sqlite3
python ops/scripts/evaluate_incidents.py --database runtime/lab/wsl.sqlite3 \
  --cases ops/lab/wsl_cases --split-file resources/evaluation/lab/wsl_split.json \
  --output resources/evaluation/lab/wsl
```
