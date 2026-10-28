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
