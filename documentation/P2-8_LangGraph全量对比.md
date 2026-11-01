# P2-8 LangGraph 全量对比：WSL 68 + Docker 81

> 目的：用 LangGraph 后端重放两套真实故障全集，与主引擎对比。
> 结论：**WSL 完全一致（67/68）；Docker LangGraph 75.3%，低于主引擎 91.4%，差距集中在心跳（14/27 vs 27/27）。**

## 1. 实验设置

| 项 | WSL | Docker |
| --- | --- | --- |
| 案例 | 68（38 卷 + 10 心跳 + 20 安全） | 81（28 卷 + 27 心跳 + 26 安全） |
| 后端 | `--agent-backend langgraph` | 同左 |
| 数据库 | `runtime/lab/lg_wsl.sqlite3` | `runtime/lab/lg_docker.sqlite3` |
| 案例副本 | `runtime/lab/lg_wsl_cases` | `runtime/lab/lg_docker_cases` |
| 报告 | 每例重新生成 | 每例重新生成 |

处理方式：复制案例与数据库 → 清空旧报告 → 逐例 `ingest --agent-backend langgraph` → 用同一评测脚本评分。

## 2. 总体结果

| 指标 | WSL 主引擎 | WSL LangGraph | Docker 主引擎 | Docker LangGraph |
| --- | --- | --- | --- | --- |
| Top-1 | **98.5%**（67/68） | **98.5%**（67/68） | **91.4%**（74/81） | **75.3%**（61/81） |
| Top-3 | 100% | 100% | 93.8% | 75.3% |
| Top-5 | 100% | 100% | 93.8% | 77.8% |
| MRR | 0.9926 | 0.9926 | 0.9218 | 0.7593 |
| 冻结测试集 | n=14，100% | n=14，100% | n=30，90.0% | n=30，73.3% |
| checkpoint | — | 1224 条 | — | 1458 条 |

## 3. 分族结果

| 故障族 | WSL 主引擎 | WSL LangGraph | Docker 主引擎 | Docker LangGraph |
| --- | --- | --- | --- | --- |
| DN_VOLUME | 38/38 | **38/38** | 21/28 | **21/28** |
| DN_HEARTBEAT | 9/10 | **9/10** | 27/27 | **14/27** |
| NN_SAFE_MODE | 20/20 | **20/20** | 26/26 | **26/26** |

## 4. 差异分析

### 4.1 WSL：完全一致

- 卷故障与安全模式都依赖强信号，候选路径与主引擎结果相同；
- 唯一失败仍是缺死亡信号的心跳案例，两边都排第 2。

### 4.2 Docker：心跳掉了 13 例

LangGraph 走的是 v1.1 候选路径：

- 检索计划由 `query_builder` 生成，**没有主引擎的“信号码硬过滤”**；
- 主引擎在检测到 `lost heartbeat / removedead` 后，会把检索池强制收窄到 `DN_HEARTBEAT` 卡；
- 候选路径没有这一步，心跳卡可能根本没进候选，或排序被卷卡压住；
- 结果就是 27/27 → 14/27。

卷故障和安全模式不受影响，因为它们的关键词更独特，检索本身就能命中。

## 5. 结论

1. **LangGraph 能跑全量**：68 + 81 全部生成报告，checkpoint 正常；
2. **WSL 与主引擎完全一致**：说明图编排本身没有引入偏差；
3. **Docker 差距可解释**：不是 LangGraph 的问题，是候选路径缺少信号码硬过滤；
4. **不能混报**：LangGraph Docker 75.3% 不能替代主引擎 91.4%，也不能把两套平均。

## 6. 复现

```powershell
# WSL
python ops/lab/harness/langgraph_poc.py

# 全量：逐例复制后重放（脚本思路见 P2-7）
python ops/lab/harness/ingest.py --case <copied_case> --database runtime/lab/lg_wsl.sqlite3 --agent-backend langgraph
python ops/scripts/evaluate_incidents.py --database runtime/lab/lg_wsl.sqlite3 --cases runtime/lab/lg_wsl_cases --output resources/evaluation/lab/langgraph_wsl
```

结果文件：

- `resources/evaluation/lab/langgraph_wsl.md`
- `resources/evaluation/lab/langgraph_docker.md`

## 7. 下一步

若要让 LangGraph Docker 追平主引擎，需要把主引擎的“信号码 → 卡片硬过滤”移植到候选路径；预计能修复大部分心跳案例，但需重新评测。
