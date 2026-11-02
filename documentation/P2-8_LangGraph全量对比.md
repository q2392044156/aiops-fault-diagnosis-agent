# P2-8 LangGraph 全量对比：WSL 68 + Docker 81

> 目的：用 LangGraph 后端重放两套真实故障全集，与主引擎对比。
> 结论：**两套数据都已追平主引擎：WSL 67/68，Docker 74/81。**

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
| Top-1 | **98.5%**（67/68） | **98.5%**（67/68） | **91.4%**（74/81） | **91.4%**（74/81） |
| Top-3 | 100% | 100% | 93.8% | 91.4% |
| Top-5 | 100% | 100% | 93.8% | 93.8% |
| MRR | 0.9926 | 0.9926 | 0.9218 | 0.9198 |
| 冻结测试集 | n=14，100% | n=14，100% | n=30，90.0% | n=30，90.0% |
| checkpoint | — | 1224 条 | — | 1458 条 |

## 3. 分族结果

| 故障族 | WSL 主引擎 | WSL LangGraph | Docker 主引擎 | Docker LangGraph |
| --- | --- | --- | --- | --- |
| DN_VOLUME | 38/38 | **38/38** | 21/28 | **21/28** |
| DN_HEARTBEAT | 9/10 | **9/10** | 27/27 | **27/27** |
| NN_SAFE_MODE | 20/20 | **20/20** | 26/26 | **26/26** |

## 4. 差异分析

### 4.1 WSL：完全一致

- 卷故障与安全模式都依赖强信号，候选路径与主引擎结果相同；
- 唯一失败仍是缺死亡信号的心跳案例，两边都排第 2。

### 4.2 Docker：补上信号码硬过滤后追平

第一次全量时 Docker LangGraph 只有 75.3%（61/81），心跳 14/27。原因是候选路径没有“信号码硬过滤”：

- 主引擎检测到 `lost heartbeat / removedead` 后，会把检索池强制收窄到 `DN_HEARTBEAT` 卡；
- 候选路径只有 `query_builder` 的通用计划，心跳卡可能没进候选。

修复：

1. 抽出 `detected_codes_from_text`，候选路径复用同一套信号检测；
2. `retrieve_runbook(..., code=...)` 把信号码一路传到检索器，检索池收窄到对应根因卡；
3. 心跳 14/27 → **27/27**，Docker 总体 75.3% → **91.4%**。

卷故障、安全模式保持 21/28、26/26 不变。

## 5. 结论

1. **LangGraph 能跑全量**：68 + 81 全部生成报告，checkpoint 正常；
2. **WSL 与主引擎逐例一致**：67/68，说明图编排没有引入偏差；
3. **Docker 补齐检索策略后追平**：74/81，心跳 27/27；
4. **图只负责路由**：指标由业务检索/排序策略决定，不是换个框架就自动变好；
5. 两套引擎数字可以并列展示，但仍不建议合并成一个“149 例准确率”。

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

已追平主引擎。若要继续提升，可把候选路径的 Top-3 合并/排序细节进一步对齐（当前 Docker Top-3 91.4% vs 主引擎 93.8%）。
