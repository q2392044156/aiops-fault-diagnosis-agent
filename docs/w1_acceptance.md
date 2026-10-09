# W1 验收报告

验收日期：2026-10-09（Asia/Shanghai）。结论：W1数据基础设施及HDFS_v1全量验收通过。尚未训练异常模型，不产生模型效果指标。

## 实际数据结果

|项目|实测结果|
|---|---|
|压缩包|186645559字节，官方MD5一致，ZIP解压通过|
|原始日志|11175629行，全部字段解析成功|
|时间范围|2008-11-09 20:35:18 至 2008-11-11 11:16:28，时区未知|
|block会话|575061|
|标签|正常558223；异常16838，与前期调研一致|
|标签问题|重复、冲突、非法、缺失、无对应日志均为0|
|坏行、无block、多不同block行|均为0；对应边界行为由自制测试覆盖|
|字段缺失、时间倒序|均为0|
|完全重复原始行|2118条，保留并报告，不静默删除|
|跨集合共享原始行|0|
|固定规则脱敏后完整序列hash跨集合重复|0；不是Drain3模板口径，不代表因果事件已独立|
|开发集|10000个完整block、233584条原始行；正常9453、异常547|
|重建|两次独立执行subset，成员清单、行成员hash与Parquet文件hash全部一致|
|抽检|固定随机200行AI辅助审阅；加负数ID样例后205行自动回读检查，全部一致|
|软件测试|20项通过；锁文件安装及uv入口验证通过；git diff --check通过|

## 初版时间划分

边界为2008-11-10 19:48:00与2008-11-11 03:32:14，两侧各600秒隔离；按时间跨度60/20/20，不是会话数量同比例。

|集合|正常|异常|合计|
|---|---:|---:|---:|
|train|105657|6197|111854|
|validation|37046|1532|38578|
|test|244597|5944|250541|
|excluded|170923|3165|174088|

排除中169367个跨时间边界，4721个进入embargo。排除比例30.273%，主要由长会话跨界造成；不为降低排除比例而拆分会话。各集合均有正例，但比例不同。W2必须审查保留集代表性，补齐事件簇代理与模板口径重复审计后冻结正式协议。

## 环境与性能范围

Python 3.11.16；PyArrow 23.0.1；PyYAML 6.0.3；pytest 9.1.1；Windows，16逻辑CPU，约31.8GiB内存。具体依赖见uv.lock。

全量build记录耗时293.375秒，批次采样RSS峰值587.61MiB。该耗时包含读取、解析、落盘及SQLite索引建立，不包含下载、后续划分/双次子集导出/审计；内存值是build阶段采样值，不冒充全流程精确峰值。

本次下载器最初请求停滞，改用系统curl完成传输后，仍由项目download命令核对官方元数据、MD5、SHA-256与解压内容。下载器已改为首次请求不带Range、续传严格验证Range，并测试重试与忽略Range情形。中断后的开发集导出重新执行；已完成build/split通过产物hash验证复用。未覆盖原调研资料。

## 复现与证据

```powershell
uv sync --locked
uv run pytest -q
uv run python -m aiops_diag.data download --config configs/data.yaml
uv run python scripts/verify_w1.py
```

详细证据位于本地被忽略的 `data/processed/b6ec93dcf0ef27974252/`：build.json、split.json、subset.json、reproduction.json、audit.json、sample_review.json。下载证据为data/raw/download.json。可提交的精简来源与hash清单见w1_manifest.json。

`audit.json`的manual_review_status仍代表尚无独立人类审核；本次Codex审阅记录见w1_sample_review.md，不将AI检查冒充人工专家标注。自动检查只证明格式/关联/重建一致，不证明标签或根因真值正确。

## 交付范围与后续

交付download/build/split/subset/audit/trace六个CLI、锁定环境、测试、数据字典、数据卡、许可说明、抽检及本报告。原始数据、大型索引和含原文抽检结果均不提交Git。

W2按w2_backlog.md继续：事件簇代理、Drain3训练拟合/冻结推断、正式划分冻结、TF-IDF+LR与评测CLI。没有实现自动处置、LLM或Web服务。

Git提交与上传由用户执行。建议commit：`feat(data): implement W1 HDFS ingestion and reproducible dataset pipeline`。
