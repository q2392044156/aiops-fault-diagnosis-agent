# 检索评测流水线

## 模块职责

从日志与知识卡片里造出 v1.1 评测题池，经独立评审后冻结成密封协议，再对冻结检索或候选智能体做盲测；runbook 覆盖与人工标注相关性也在这一层汇总。

## 依赖边界

可以读 `online/knowledge/`（协议校验、冻结检索、指标与门控），也可以读 `online/diagnosis/`（服务配置、候选发布核验）；反过来两个包都不依赖本目录。

## Python 文件说明

| 文件 | 主要功能 | 主要类或函数 |
| --- | --- | --- |
| `__init__.py` | 定义当前包的公共入口、版本或导出符号。 | — |
| `blind.py` | 在冻结知识库与候选智能体上跑盲测，落盘对照指标。 | `run` |
| `freeze.py` | 把评审通过的候选池冻结成密封协议目录。 | `freeze` |
| `pool.py` | 从日志与知识卡片造复核题包，供独立评审选证据单元。 | `validate`、`build_packet` |
| `review.py` | 校验评审交回的标注与题包结构、可见性边界。 | `validate_packet`、`validate_submission` |
| `runbook.py` | 生成 runbook 盲评包、统计返回覆盖、评分后核对相关性。 | `coverage`、`build`、`evaluate` |

## 阅读建议

先读 `pool.py` 看题怎么来，再看 `review.py` 与 `freeze.py` 看题怎么被验收并密封；`blind.py` 是跑分入口，`runbook.py` 只管"返回了没有"和"标注意见是什么"，不产出相关性结论。
