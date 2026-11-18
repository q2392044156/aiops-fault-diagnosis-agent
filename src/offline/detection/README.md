# 异常检测

## 模块职责

训练与评估 LR、LSTM 等日志异常检测模型。

## 依赖边界

依赖数据契约；不依赖诊断编排和服务接口。

## Python 文件说明

| 文件 | 主要功能 | 主要类或函数 |
| --- | --- | --- |
| `__init__.py` | 定义当前包的公共入口、版本或导出符号。 | — |
| `__main__.py` | 实现 `python -m` 命令行入口和参数分发。 | `inspect`、`main` |
| `settings.py` | 三套运行配置的读取、派生字段回填与哈希。 | `load`、`load_lstm`、`load_selection`、`resolved` |
| `mining.py` | 按日志来源构建并加载 Drain3 模板。 | `build`、`SourceTemplateMatcher` |
| `novelty.py` | 基于正常模板集合计算窗口新颖度。 | `TemplateNoveltyDetector` |
| `report.py` | 计算当前模块的评测指标并输出结构化结果。 | `_false_positive_events`、`_fmt`、`_publish_docs`、`evaluate` |
| `lstm_model.py` | 实现 LSTM 异常检测网络结构。 | `seed_everything`、`resolve_device`、`SequenceDataset`、`collate_sequences`、`LSTMClassifier` |
| `lstm_workflow.py` | 执行 LSTM 训练、验证、保存和推理。 | `_load_data`、`_make_loader`、`_move`、`_score`、`training_weight`、`_train_once`、`_overfit_check` 等 |
| `metrics.py` | 计算 Precision、Recall、F1、AUC 等检测指标。 | `_ratio`、`classification_metrics`、`select_threshold`、`pr_curve` |
| `model.py` | 实现日志模板特征与逻辑回归检测器。 | `_load_rows`、`_document`、`_rule_scores`、`_isolation_features`、`_apply_threshold`、`_aggregate`、等 |
| `protocol.py` | 冻结数据划分、随机种子和检测评测协议。 | `_labels`、`_first_messages`、`_event_clusters`、`_sample_groups`、`freeze` |
| `sequences.py` | 构造 LSTM 所需的日志事件序列和张量。 | `_fraction`、`role_for`、`_upstream`、`_scaler`、`prepare_sequences` |
| `features.py` | 抽取与规范化日志模板特征。 | `content`、`miner_config`、`_membership`、`_selected`、`_candidate_review`、`_empty_state`、`_add`、`_write_sessions` 等 |
| `runs.py` | 三轮离线检测共用的 run_id、git 提交、清单校验与发布。 | `git_commit`、`run_name`、`stage`、`publish` |

## 阅读建议

先阅读配置或 Schema，再阅读核心引擎，最后查看 `workflow.py`、`__main__.py` 或验收脚本了解完整调用顺序。文件内的中文注释重点解释职责、输入参数、数据字段和关键约束。
