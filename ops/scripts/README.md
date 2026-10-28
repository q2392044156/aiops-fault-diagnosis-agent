# 运维与验收脚本

## 模块职责

执行离线评测、在线验收、恢复演练和数据准备。

## 依赖边界

脚本调用公开 Python 接口，不承载可复用业务逻辑。

## Python 文件说明

| 文件 | 主要功能 | 主要类或函数 |
| --- | --- | --- |
| `acceptance_w10.py` | 执行评测或验收并输出机器可读结果。 | `wait_for`、`main` |
| `benchmark_w6_containers.py` | 运行基准测试并记录耗时与资源指标。 | `wait_ready`、`compose`、`main` |
| `build_framework_rc2_acceptance_manifest.py` | 执行评测或验收并输出机器可读结果。 | `load_json`、`sha256`、`evidence`、`main` |
| `evaluate_incidents.py` | 用 incident 标签与报告计算 Top-1/Top-3/MRR/MTTD。 | `evaluate`、`markdown` |
| `run_redteam.py` | 运行红队用例并输出拦截率与误杀率。 | `main` |
| `mcp_smoke.py` | 以子进程方式冒烟验证 MCP 服务器。 | `_rpc`、`main` |
| `evaluate_context.py` | 对同一批报告做上下文策略消融并输出对比表。 | `_load_env`、`_client`、`_cases`、`_citation_check`、`main` |
| `evaluate_trajectory.py` | 读取服务数据库并输出诊断轨迹指标。 | `_rows`、`main` |
| `evaluate_router.py` | 运行工具路由三模式对照实验并输出对比表。 | `_load_env`、`_client`、`_deterministic`、`_constrained`、`_free`、`main` |
| `evaluate_v12.py` | 执行评测或验收并输出机器可读结果。 | `main` |
| `prepare_v12_external_datasets.py` | 实现 prepare v12 external datasets 相关的辅助流程。 | `main` |
| `run_framework_chain_online_smoke.py` | 执行关键路径冒烟验证。 | `load_local_secrets`、`run` |
| `run_framework_flow_smoke.py` | 执行关键路径冒烟验证。 | `wait_for`、`run` |
| `run_framework_offline_comparison.py` | 实现 run framework offline comparison 相关的辅助流程。 | — |
| `run_framework_rc2_fault_recovery_acceptance.py` | 执行评测或验收并输出机器可读结果。 | `render` |
| `run_framework_rc2_offline_acceptance.py` | 执行评测或验收并输出机器可读结果。 | `render` |
| `run_framework_rc2_online_acceptance.py` | 执行评测或验收并输出机器可读结果。 | `load_secret_environment`、`percentile`、`render` |
| `run_framework_rc2_rollback_drill.py` | 实现 run framework rc2 rollback drill 相关的辅助流程。 | — |
| `run_framework_rc2_sealed_acceptance.py` | 执行评测或验收并输出机器可读结果。 | `read_jsonl`、`percentile`、`ranking_metrics`、`render` |
| `smoke_w6.py` | 执行关键路径冒烟验证。 | `main` |
| `validate_framework_rc2_docs.py` | 校验输入、产物和运行条件是否满足约定。 | `digest`、`markdown_missing_links`、`iter_text_files`、`main` |
| `validate_project_structure.py` | 检查功能目录、模块 README、旧包引用和中文源码说明。 | `_module_readme_errors`、`_source_comment_errors`、`validate`、`main` |
| `validate_v12_online.py` | 校验输入、产物和运行条件是否满足约定。 | `_prepare`、`_choose_events`、`run`、`main` |
| `verify_w1.py` | 校验输入、产物和运行条件是否满足约定。 | `main` |
| `w9_api_smoke.py` | 执行关键路径冒烟验证。 | `main` |

## 阅读建议

先阅读配置或 Schema，再阅读核心引擎，最后查看 `workflow.py`、`__main__.py` 或验收脚本了解完整调用顺序。文件内的中文注释重点解释职责、输入参数、数据字段和关键约束。
