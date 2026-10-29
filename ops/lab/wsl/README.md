# WSL 单机 HDFS 实验台

Hadoop **3.3.6**（稳定、社区常用）+ OpenJDK 11，跑在 WSL2 Ubuntu 24.04，数据目录是 **64MB ext4 loop 镜像**。

## 安装位置

| 项 | 路径 |
| --- | --- |
| Hadoop | `/opt/lab/hadoop`（软链到 `hadoop-3.3.6`） |
| 配置 | `/opt/lab/hadoop/etc/hadoop/{core-site,hdfs-site}.xml` |
| NameNode 元数据 | `/opt/lab/data/name` |
| DataNode 数据 | `/mnt/labvol`（loop 挂载） |
| 日志 | `/opt/lab/nn.log`、`/opt/lab/dn.log` |

关键配置：`dfs.replication=1`、`dfs.blocksize=4194304`、`dfs.permissions.enabled=false`。

## 脚本

```bash
# 重建 64MB ext4 loop 并重启 DataNode
bash ops/lab/wsl/reset_volume.sh

# 连续写 1MB 块，直到 NameNode 拒绝分配
bash ops/lab/wsl/experiment_volume.sh <输出目录>
```

## 当前状态（2026-10-29）

- NameNode + DataNode 正常启动，容量约 **55MB**；
- 连续写入可把卷填到 **99%（992KB 剩余）**；
- 但 **DN 侧没有打出 `DiskOutOfSpaceException`**：NameNode 在剩余空间小于块大小时先拒绝分配，写请求到不了 DN。

## 下一步选项

1. 用 `dfs.datanode.du.reserved` 让 DN 自报"剩余不足"，触发 DN 侧检查；
2. 停 DN 后把 loop 卷 remount 成只读，再启动 DN，制造真实卷故障；
3. 用 `dmsetup` error target 模拟 IO 错误（需要 device-mapper）。

## 卷故障：只读 remount（已验证，推荐）

```bash
bash ops/lab/wsl/readonly_volume.sh <输出目录>
```

流程：停 DataNode → 把 loop 卷 remount 成 `ro` → 启动 DataNode → 采集失败日志 → remount `rw` 并重启 DataNode。

实测结果：

- DataNode 启动即失败，日志记录：
  `DiskChecker$DiskErrorException: Too many failed volumes - current valid volumes: 0, volumes configured: 1, volumes failed: 1`
- 恢复后 `Live datanodes (1)` 正常；
- 证据文件：`documentation/results/wsl_volume/readonly_evidence.txt`。

这条路径不依赖 ENOSPC，适合作为 `DN_VOLUME` 的稳定注入方式。

## 端到端实验（已验证 5/5）

```bash
python ops/lab/wsl/run_case.py --database runtime/lab/wsl.sqlite3
```

流程：停 DN → remount `ro` → 启 DN（失败）→ 采日志 → 恢复 `rw` → 重启 DN → 生成 incident → 接入诊断 → 回填 map。

2026-10-29 实测 5 例：

| 指标 | 值 |
| --- | --- |
| 事件数 / 有报告 | 5 / 5 |
| Top-1 | **1.0** |
| Top-3 | 1.0 |
| MRR | 1.0 |
| Top-1 95% CI | [0.5655, 1.0] |
| 恢复 | 5/5 `Live datanodes (1)` |

关键修复：容器/WSL 日志里没有时间戳的行（如 `DiskErrorException`）此前会被排到末尾并截断；现在用 incident 的 `fault_start` 兜底，保证关键行进入证据。

## 批量结果（2026-10-29，68 例）

| 故障族 | n | Top-1 |
| --- | --- | --- |
| DN_VOLUME（只读 remount） | 38 | 1.0 |
| DN_HEARTBEAT（kill + 2s 心跳） | 10 | 1.0 |
| NN_SAFE_MODE（safemode enter/leave） | 20 | 1.0 |
| 合计 | **68** | **1.0**（Top-3/5 均 1.0，95% CI [0.9465, 1.0]） |

说明：

- 心跳注入需要 `dfs.heartbeat.interval=2` + `recheck-interval=2000`，已写入 WSL 的 `hdfs-site.xml`；
- 部分案例 `live_recovered=false`：`nohup hdfs datanode &` 在 wsl 会话退出后可能被回收，建议改用 `hdfs --daemon start datanode`；
- 21 份证据在 `ops/lab/wsl_cases/`。

## 范围说明（定稿）

卷故障只保留"只读 remount"这一形态。真实 ENOSPC 被 NameNode 容量预检挡住；WSL 的 `dmsetup targets` 只有 `verity/striped/linear/error`，没有 `flakey`，无法做 `error_writes` 的 IO 故障注入。因此 48 例 100% 只代表"只读卷故障 + 心跳丢失"。
