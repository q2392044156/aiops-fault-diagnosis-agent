# v1.0 验收记录

候选：`v1.0-rc2`
产品候选哈希：`04591f6e2a6237ca15b72913b38ed6aca7ae1790d0a372a3d9ff5dafb401d4c1`
结论：**RELEASED**（安全与复现门禁全部通过）

| 验收项 | 结果 | 证据 |
|---|---|---|
| Atest 40 例确定性回放 | 通过 | 本地 `experiments/w10/atest_replay_summary.json` |
| Atest 40 例 × 3 次真实 DeepSeek | 通过 | 本地 `experiments/w10/atest_online_summary.json` |
| 强制复核漏转 | 0 | Task/Review 汇总指标 100% |
| 非法引用、越权工具、写操作 | 0 | 三轮逐例安全统计 |
| `execution_allowed=true` | 0 | 回放、在线和容器链路 |
| Token/费用/工具/时间硬限制 | 未突破 | 三轮预算统计；总成本 ¥0.426384 |
| 审批身份、版本、过期、冲突 | 通过 | API 回归与容器未认证 401 |
| 崩溃恢复与幂等 | 通过 | 重启后状态 `APPROVED_REPORT`，工具调用未重复 |
| 全部测试 | 100/100 通过 | 11.57 秒，`pip check` 通过 |
| 全新 Python 3.11.17 环境 | 通过 | 本地 `environment_acceptance.json` |
| 无缓存 Compose 构建 | 通过 | Linux CPU 镜像，镜像内 `pip check` 通过 |
| API / worker / UI 健康 | 通过 | 独立项目 `aiops-v1-acceptance` |
| 容器安全边界 | 通过 | UID 10001、只读根、cap-drop ALL、无 socket/Torch/CUDA |
| 离线模式 | 通过 | 模板报告、0 外部调用 |
| 在线 Secret 覆盖 | 通过 | DeepSeek HTTP 200；Schema 失败安全降级 |
| Docker 数据目录在 E 盘 | 通过 | Desktop `CustomWslDistroDir=E:/develop/docker/wsl` |
| 敏感信息进入 Git | 0 | 最终敏感信息扫描 |

## 实测差距

- 报告 Schema 通过率为 93.33% ± 11.55%，模板降级率为 6.67% ± 11.55%。降级过程安全、可审计，但输出稳定性仍需提高。
- Rtest 无答案误返回率为 20%，弱于 Rdev 的 10%。测试结果未用于反向调参。
- LLM 可选工具路由在 W9 只有 55% 准确率，因此 v1.0 默认关闭；该指标在 W10 记为 N/A。
- HDFS_v1 无真实根因标签，根因准确率和生产 MTTD 均为 N/A。

## 验收中修复的阻断缺陷

1. 在线评测发现未决预算预留可能长期保持 `RESERVED`；rc2 增加保守结算与回归测试。
2. 无缓存容器首次启动发现镜像缺少评测协议文件；Dockerfile 已纳入版本化协议。
3. 登记批次首次请求发现 API 无只读数据挂载；Compose 已同时挂载给 API 和 worker。
4. 默认端口被现有实例占用；宿主绑定端口改为可配置，验收未停止或覆盖现有服务。

验收创建的独立容器、网络和命名卷已用 `down -v` 清理；现有服务和数据未被删除。
