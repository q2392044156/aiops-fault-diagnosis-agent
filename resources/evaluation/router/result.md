| 模式 | 完全一致 | 精确率 | 召回率 | F1 | 多余调用率 | 漏调率 | 平均 tokens | 平均延迟 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deterministic | 20.00% | 100.00% | 0.00% | 0.00 | 0.00% | 100.00% | 0 | 0 ms |
| free | 66.67% | 75.56% | 100.00% | 0.86 | 24.44% | 0.00% | 156 | 980 ms |
| rules | 93.33% | 96.97% | 94.12% | 0.96 | 3.03% | 5.88% | 285 | 739 ms |
| constrained | 90.00% | 91.67% | 97.06% | 0.94 | 8.33% | 2.94% | 863 | 1030 ms |

| 模式 | 工具 | 命中 | 误报 | 漏报 |
| --- | --- | --- | --- | --- |
| deterministic | query_metrics | 0 | 0 | 17 |
| deterministic | read_trace_summary | 0 | 0 | 9 |
| deterministic | search_similar_incidents | 0 | 0 | 8 |
| free | query_metrics | 17 | 4 | 0 |
| free | read_trace_summary | 9 | 2 | 0 |
| free | search_similar_incidents | 8 | 5 | 0 |
| rules | query_metrics | 17 | 1 | 0 |
| rules | read_trace_summary | 8 | 0 | 1 |
| rules | search_similar_incidents | 7 | 0 | 1 |
| constrained | query_metrics | 17 | 2 | 0 |
| constrained | read_trace_summary | 9 | 1 | 0 |
| constrained | search_similar_incidents | 7 | 0 | 1 |
