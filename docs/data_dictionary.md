# W1 数据字典

原始数据、处理输出、标签及本地索引均位于 Git 忽略的 data/。默认输出目录以原始文件SHA-256和语义配置hash定版本；绝对路径和磁盘门槛不参与版本。

|字段/产物|定义|
|---|---|
|log_id|完整源文件SHA-256 + 冒号 + 从1开始的原始行号|
|raw_line_no / byte_offset / byte_length|原始二进制行号、从0开始的字节偏移、含换行的长度|
|raw_hash|原始行字节（含换行）的SHA-256|
|timestamp_original|日志原始YYMMDD HHMMSS|
|timestamp_local|无时区ISO时间；仅在本数据集内部作相对时间比较|
|timestamp_utc / timezone_assumption|未知时区时为空 / unknown|
|pid / level / component / message|源日志字段；PID仅用于追溯，不是模型特征|
|session_ids|本行全部不同block ID，排序后存储；包括负数ID|
|parse_status|ok / decode_error / format_error / time_error|
|links.parquet|block_id和raw_line_no，保存多对多关联|
|index.sqlite|lines定位表、links关联表、sessions时间/坏行/长度/序列hash摘要；无原始全文|
|splits.parquet|block_id、group_id、split、reason；group_id取连通组字典序最小block|
|groups.json|组划分、排除原因及block数|
|dev_members.json / dev_logs.parquet|完整开发组成员及其所有去重原始行的解析结果|

logs.parquet是追溯数据，不可整表直接作为模型输入；其ID、PID、原文内IP/ID均不得作为模型特征。W1仅计算level/component及固定规则掩码消息构成的序列hash，W2建立严格白名单特征接口。

标签只在audit阶段读取，独立保存在raw/anomaly_label.csv；所有解析、分组、抽样接口均不读取标签。审计输出属于评测元数据，不能进入Agent上下文。

时间切分：全局有效会话时间跨度60/20/20；左闭右开，末区间包含最大时间。共享行block传递连接成组。跨界、边界前后600秒、含坏行的整组排除。初版不包含真实故障事件真值或事件簇代理。

完整序列hash：按原始文件行序，移除block和IP、掩码数值；每条内容使用4字节无符号大端长度前缀避免串接歧义（单行小于4GiB）。不删除跨集合相同序列，审计单独报告；严格去重和Drain3模板口径留W2。
