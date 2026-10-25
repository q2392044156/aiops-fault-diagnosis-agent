# 项目目录与依赖说明

## 顶层目录

```text
aiops-fault-diagnosis-agent/
├─ src/aiops_diag/       # 可复用的 Python 业务源码
│  ├─ data/              # 数据接入、脱敏和标准化
│  ├─ detection/         # 异常检测和模型选择
│  ├─ knowledge/         # 知识检索和证据约束报告生成
│  ├─ diagnosis/         # Agent、查询规划和 LangGraph 编排
│  ├─ evaluation/        # legacy/framework 对照评测
│  ├─ platform/          # FastAPI、worker、SQLite 和界面
│  └─ release/           # 发布清单与哈希校验
├─ resources/            # 配置、知识卡和冻结评测协议
├─ ops/                  # 部署文件、运维和验收脚本
├─ documentation/        # 技术报告、验收结果和演示资料
└─ tests/                # 自动化测试
```

`data/`、`artifacts/`、`experiments/` 和 `runtime/` 是本地输入或运行产物，继续由 `.gitignore` 隔离，不属于 Python 源码。早期阶段报告统一存放在 `documentation/archive/` 并保持忽略。

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
