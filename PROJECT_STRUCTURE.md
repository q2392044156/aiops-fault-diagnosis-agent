# 项目目录与依赖说明

## 顶层目录

```text
aiops-fault-diagnosis-agent/
├─ src/
│  ├─ offline/           # 离线数据流程一级入口
│  │  ├─ ingestion/      # 解析、脱敏、滑动窗口
│  │  └─ case/           # 故障事件契约、导入与受控实验记录、来源模板与新颖度门禁
│  ├─ online/            # 在线诊断流程一级入口
│  │  ├─ knowledge/      # 语料、混合检索与发布；v11/ 评测、generation/ 报告生成
│  │  └─ diagnosis/      # 7 节点代理、工具、证据与路由；v11/ 候选、framework/ LangGraph
│  ├─ evaluation/        # 跨离线/在线的评测层：轨迹、红队、路由与框架对照
│  └─ aiops_diag/        # 共享基础设施与产品发布
│     ├─ common.py       # 哈希、配置解析、清单校验、分位数
│     ├─ constants.py    # 工具白名单与预算裁剪顺序
│     ├─ nodes.py        # 诊断节点固定顺序
│     ├─ platform/       # FastAPI、worker、SQLite、Streamlit、MCP 与 incident 命令
│     └─ release/        # 产品发布冻结与验收（python -m aiops_diag.release）
├─ resources/            # 配置、知识卡与评测结果
├─ ops/                  # 脚本、红队用例、WSL/Docker 实验台
├─ demo/                 # 离线端到端演示
├─ documentation/        # 报告、架构与验收记录
└─ tests/                # 自动化测试
```

`data/`、`artifacts/`、`experiments/`、`runtime/` 和 `ops/lab/*_cases/` 是本地输入、运行产物或实验数据集，由 `.gitignore` 隔离，不属于 Python 源码。早期阶段报告统一存放在 `documentation/archive/` 并保持忽略。文档导航见 [documentation/README.md](documentation/README.md)。

## 依赖方向

```text
aiops_diag（common / constants / nodes）← 所有模块

offline.ingestion → offline.case

online.knowledge → online.diagnosis

evaluation → offline + online
```

`offline` 和 `online` 是稳定流程入口，复用 `src/aiops_diag` 的基础设施。`evaluation` 是唯一允许同时依赖 `offline` 与 `online` 的层，两侧都不得反向依赖它。

下层模块只提供数据结构或稳定接口，上层模块负责组合。`platform` 是运行时组合根；`ops` 只调用公开入口；`tests` 可以依赖所有模块。禁止业务模块反向导入 `platform`、`ops` 或 `tests`，也禁止 `offline` 导入 `online`。

## 命名约定

- 同一种角色在不同包里同名：`settings.py` 只做配置读取，`release.py` 只做哈希冻结与校验，`agent.py` 只做节点推进，`README.md` 只描述目录职责。
- 文件名要能回答"这个模块负责哪一步"，不用 `models.py`、`workflow.py`、`config.py` 这类在四个包中含义不同的名字。

## 兼容约定

- HTTP API 路径和请求响应 Schema 保持兼容。
- 服务后端仍由启动配置选择，普通 API 请求不能切换实现。
- SQLite 继续作为任务、预算、审批和审计的权威来源。
- 所有诊断建议保持 `execution_allowed=false`。

## 静态检查

静态检查只用两条命令，都在仓库根目录跑：

```bash
python -m ruff check
python -m mypy
```

`ruff` 覆盖 `src`、`tests`、`ops`、`demo`，规则集在 `pyproject.toml` 的 `[tool.ruff.lint]` 里。`T201`（`print`）是全域开启的：库代码不允许打印，命令行入口的输出要进 `per-file-ignores` 白名单，新增一个会打印的入口就得同时加白名单，这样"调试残留 print"和"命令行输出"在配置里是分开的两件事。

`mypy` 只检查 `[tool.mypy] files` 里列出的边界模块，用的是非严格模式（`ignore_missing_imports` + `check_untyped_defs`，不开 `disallow_untyped_defs`）。标注按三层：跨包公共边界标全，包内辅助只标返回值，命令行入口不标。`ops/scripts/validate_project_structure.py` 会读这份 `files` 清单，要求其中每个函数都有返回标注——所以要扩大类型覆盖，改的是 `pyproject.toml` 一处，校验规则自动跟着走。
