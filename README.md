# AIOps Fault Diagnosis Agent

面向公开HDFS日志的个人研究原型。W1实现可追溯的数据准备、初版时间划分与审计；后续建立异常检测、证据检索和人工复核。不执行自动修复。

**W1已完成全量验收（2026-10-09）**：11175629行、575061会话；可重建开发集10000会话/233584行；20项测试通过。结果与局限见[验收报告](docs/w1_acceptance.md)。

## 环境与运行

Windows / PowerShell，Python 3.11，uv。首次使用可运行 `uv python install 3.11`。依赖锁定于uv.lock；缓存位于项目.uv-cache，虚拟环境位于.venv。

```powershell
uv sync --locked
uv run python -m aiops_diag.data download --config configs/data.yaml
uv run python -m aiops_diag.data build --config configs/data.yaml
uv run python -m aiops_diag.data split --config configs/data.yaml
uv run python -m aiops_diag.data subset --config configs/data.yaml
uv run python -m aiops_diag.data audit --config configs/data.yaml
uv run pytest
```

须从项目根目录执行。全量运行前至少20GB可用磁盘；处理逐批进行，仍需为约57万会话摘要预留内存。数据输出位于data/processed/<版本>/，全部被Git忽略。

追溯原文：`uv run python -m aiops_diag.data trace --log-id '<源文件SHA256>:<行号>'`。

下载验证Zenodo元数据、大小和MD5；已有完整包可复用，残包保留.partial用于重试。阶段完成后才写manifest，复用前检查产物hash。中断build时保留半成品并明确报错；检查后可把该版本目录重命名为备份再重跑，不会自动覆盖半成品。

开发集重建：再次运行subset，比较subset.json的membership_hash、line_membership_hash及dev_logs.parquet hash。审计样本保留本地原文，sample_review.json中的自动检查不等于人工审阅，人工结论单独记录。

## 文档与边界

- [数据字典](docs/data_dictionary.md)
- [数据卡](docs/dataset_card.md)
- [W2待办](docs/w2_backlog.md)
- [W1抽检记录](docs/w1_sample_review.md)
- [W1精简manifest](docs/w1_manifest.json)

W1初版划分按时间60/20/20与10分钟embargo，完整共享行组隔离。标签独立审计，不参与解析或抽样。Drain3、正式协议冻结及模型训练留W2。训练、验证、测试可能含相同正常模式，跨集合序列重复会单列；不将其误称零泄漏的最终实验协议。

请只提交代码、配置、锁文件、文档和自制测试；data/中原始数据、索引、逐行清单及抽检原文不提交。
