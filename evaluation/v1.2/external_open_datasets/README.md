# v1.2 公开数据接入协议

本目录定义 LogHub Hadoop 与 HDFS v3 TraceBench 的接入边界。执行入口：

```powershell
$env:PYTHONPATH = "src"
python -m aiops_diag.data v12-external prepare --config configs/data_v12_external.yaml
python -m aiops_diag.data v12-external audit --config configs/data_v12_external.yaml
```

## 数据单元

- LogHub Hadoop：一个 application 是一个事件，同一 Hadoop cluster timestamp 归为同一切分组。
- TraceBench：一个采集场景目录是一个事件，同一注入脚本或场景族归为同一切分组。
- 标准记录只保存统计量、公开标签和原始文件哈希，不复制原始日志、IP、主机名或描述文本。
- 原始目录只读使用；所有生成内容进入 `data/external/loghub/processed` 和 `data/external/loghub/splits`。
- `diagnostic_snapshots.jsonl` 只含诊断时可见的数据；`evaluation_labels.jsonl` 单独保存评测标签，服务导入器不会读取标签字段。
- 服务导入使用 `python -m aiops_diag.data v12-external import-service`，相同事件和相同快照哈希会幂等去重，内容冲突会拒绝。

## 标签边界

公开数据中的正常/异常和故障注入类型写入 `anomaly_label` 与 `injection_label`。`root_cause_label` 固定为 `null`，因为这些标签没有按照真实事故协议经过工单、复盘和独立人员确认。

公开数据可以计算单独命名的故障注入基准指标。生产根因 Top-1、Top-3、MRR 和 MTTD 均保持 `N/A`。

## 切分协议

- Hadoop 按采集运行批次完整分组。
- TraceBench 按故障脚本/场景族完整分组，并在正常、注入故障和组合场景内分别确定性划分。
- 同一组不得跨 development、calibration 和 independent_test。
- 数据和标签均已公开，因此 `independent_test` 只是组隔离的公开测试分区，不是封存盲测集。

结构定义见 `event.schema.json`。每次处理都会生成数据审计、泄漏审计和带 SHA-256 的清单。
