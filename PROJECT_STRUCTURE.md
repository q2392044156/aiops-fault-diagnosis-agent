# 项目目录与依赖说明

## 顶层目录

```text
aiops-fault-diagnosis-agent/
├─ src/aiops_diag/       # 可复用的 Python 业务源码
│  ├─ data/              # 接入、脱敏、incident 协议与实验记录
│  ├─ detection/         # 异常检测和模型选择
│  ├─ knowledge/         # 知识检索和证据约束报告生成
│  ├─ diagnosis/         # Agent、工具、路由、上下文与编排
│  ├─ evaluation/        # 轨迹、路由、红队与框架对照评测
│  ├─ platform/          # FastAPI、worker、SQLite、Streamlit、MCP
│  └─ release/           # 发布清单与哈希校验
├─ resources/            # 配置、知识卡与评测结果
├─ ops/                  # 脚本、红队用例、WSL/Docker 实验台
├─ demo/                 # 离线端到端演示
├─ documentation/        # 报告、架构与验收记录
└─ tests/                # 自动化测试
```

`data/`、`artifacts/`、`experiments/`、`runtime/` 和 `ops/lab/*_cases/` 是本地输入、运行产物或实验数据集，由 `.gitignore` 隔离，不属于 Python 源码。早期阶段报告统一存放在 `documentation/archive/` 并保持忽略。文档导航见 [documentation/README.md](documentation/README.md)。

## 依赖方向

```text
data → detection ─┐
                  ├→ diagnosis → platform
knowledge ────────┘       │
                          ├→ evaluation
                          └→ release
```

下层模块只提供数据结构或稳定接口，上层模块负责组合。`platform` 是运行时组合根；`ops` 只调用公开入口；`tests` 可以依赖所有模块。禁止业务模块反向导入 `platform`、`ops` 或 `tests`。

## 兼容约定

- HTTP API 路径和请求响应 Schema 保持兼容。
- 服务后端仍由启动配置选择，普通 API 请求不能切换实现。
- SQLite 继续作为任务、预算、审批和审计的权威来源。
- 所有诊断建议保持 `execution_allowed=false`。
