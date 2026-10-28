# 路线 A：本机 HDFS 故障实验台

1 个 NameNode + 3 个 DataNode，跑在 Docker Compose 里。可以注入三类故障，产出符合 `incident.schema.json` 的记录。

## 启动与停止

```powershell
docker compose -f ops/lab/compose.yaml up -d
docker exec aiops-lab-namenode hdfs dfsadmin -report   # 确认 Live datanodes (3)
docker compose -f ops/lab/compose.yaml down -v         # 停止并清理
```

## 跑一次实验

```powershell
# 不依赖 Docker，生成同形样本（用于联调）
python ops/lab/harness/run_case.py --fault DN_VOLUME --dry-run --import-db runtime/lab/mvp.sqlite3

# 真实集群
python ops/lab/harness/run_case.py --fault NN_SAFE_MODE --observe 25 --import-db runtime/lab/mvp.sqlite3

# 接入诊断并回填 map.json（批次/事件/诊断/报告）
python ops/lab/harness/ingest.py --case ops/lab/cases/<incident_id> --database runtime/lab/mvp.sqlite3

# 批量 20 例（dry-run 生成器，7+7+6）
python ops/lab/harness/run_batch.py --per-fault 7 --database runtime/lab/batch.sqlite3

# 同一个批量脚本，真实集群（每例约 40s）
python ops/lab/harness/run_batch.py --real --per-fault 7 --observe 15 --database runtime/lab/real_batch.sqlite3
```

产物在 `ops/lab/cases/<incident_id>/`：

```text
incident.json                  # 符合冻结 Schema
map.json                       # incident ↔ diagnosis/report 的旁路映射
evidence/logs/*.log            # 脱敏后的容器日志
evidence/metrics/*.csv         # docker stats 采样
evidence/tickets/*.md          # 中性值班记录（不含故障类型）
```

## 故障矩阵

| 故障族 | 容器 | 注入 | 观测信号 | 恢复 |
| --- | --- | --- | --- | --- |
| `DN_VOLUME` | aiops-lab-dn1（**64MB ext4 loop 镜像**） | 写 4MB 块填满 | `DiskOutOfSpaceException: Out of space` | 重建 loop / 删块 |
| `DN_HEARTBEAT` | aiops-lab-dn2 | `docker kill` | `Lost DataNode` / heartbeat | `docker start` |
| `NN_SAFE_MODE` | aiops-lab-namenode | `hdfs dfsadmin -safemode enter` | `Safe mode is ON` | `-safemode leave` |

## 卷满：已迁移到 WSL

Docker Desktop 的 loop 在反复挂载后不可用（`losetup` 返回 rc=1），相关脚本与 mkfs 镜像已移除。卷故障实验改用 **WSL 单机 Hadoop**：

- 安装与脚本：[wsl/](wsl/)
- 只读卷注入证据：[documentation/results/wsl_volume/readonly_evidence.txt](../../documentation/results/wsl_volume/readonly_evidence.txt)

## 设计约束

- **快照截止**：日志与指标只采集到 `cutoff = fault_start + observe`，恢复动作在 cutoff 之后执行；
- **证据脱敏**：block、IP、路径、十六进制统一替换，哈希写进 `content_sha256`；
- **标签可信**：`confidence=confirmed`、`review_status=reviewed`，并记录 creator/reviewer；
- **不自动执行运维动作**：恢复动作只针对实验台容器。