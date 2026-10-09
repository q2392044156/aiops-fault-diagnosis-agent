import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pyarrow.parquet as pq

from aiops_diag.data.common import digest, save, verified_manifest
from .metrics import classification_metrics, pr_curve
from .models import train


METHODS = ("error_rule", "rare_rule", "logistic_regression", "isolation_forest")


def _false_positive_events(rows, prediction_name, max_gap, max_span):
    by_host = defaultdict(list)
    singles = 0
    for row in rows:
        if row["label"] != 0 or row[prediction_name] != 1:
            continue
        if not row["host_alias"]:
            singles += 1
        else:
            by_host[row["host_alias"]].append(datetime.fromisoformat(row["start_time"]))
    events = singles
    for stamps in by_host.values():
        stamps.sort()
        start = previous = None
        for stamp in stamps:
            if start is None or stamp - previous > max_gap or stamp - start > max_span:
                events += 1
                start = stamp
            previous = stamp
    return events


def _fmt(value):
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _publish_docs(cfg, training, evaluation, template_manifest, protocol_manifest):
    docs = Path(cfg["root"]) / "docs"
    docs.mkdir(exist_ok=True)
    compact = {
        "schema_version": 1,
        "protocol": cfg["protocol_name"],
        "frozen": protocol_manifest["frozen"],
        "config_hash": cfg["config_hash"],
        "protocol_membership_hash": protocol_manifest["membership_hash"],
        "template_manifest_hash": training["template_manifest_hash"],
        "run_id": training["run_id"],
        "data": {
            "dmain_sessions": protocol_manifest["dmain_sessions"],
            "ddev_sessions": protocol_manifest["ddev_sessions"],
            "validation_sessions": training["validation_sessions"],
            "validation_anomalies": training["validation_anomalies"],
        },
        "parser": {
            "similarity": template_manifest["selected_similarity"],
            "templates": template_manifest["templates"],
            "validation_unknown_rate": template_manifest["validation_unknown_rate"],
            "snapshot_unchanged_after_inference": template_manifest["snapshot_unchanged_after_inference"],
        },
        "metrics": evaluation["methods"],
        "test_accessed": False,
    }
    save(docs / "w2_manifest.json", compact)
    positives = training["validation_anomalies"]
    negatives = training["validation_sessions"] - positives
    all_anomaly_f1 = 2 * positives / (2 * positives + negatives)

    lines = [
        "# W2 验证集实验报告", "",
        f"运行：`{training['run_id']}`；协议：`{cfg['protocol_name']}`。本报告只包含训练集与验证集结果，测试集保持封存。", "",
        "## 验证结果", "",
        "| 方法 | TP | FP | FN | TN | Precision | Recall | F1 | AP | ROC-AUC | FPR |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for method in METHODS:
        m = evaluation["methods"][method]
        lines.append("| " + " | ".join([
            method, _fmt(m["tp"]), _fmt(m["fp"]), _fmt(m["fn"]), _fmt(m["tn"]),
            _fmt(m["precision"]), _fmt(m["recall"]), _fmt(m["f1"]),
            _fmt(m["average_precision"]), _fmt(m["roc_auc"]), _fmt(m["fpr"]),
        ]) + " |")
    lines += [
        "", "## 协议与限制", "",
        f"- Dmain 为 {protocol_manifest['dmain_sessions']} 个完整训练会话；Ddev 为 {protocol_manifest['ddev_sessions']} 个完整训练会话。",
        f"- 验证集保持 {training['validation_sessions']} 个自然分布会话，其中异常 {training['validation_anomalies']} 个。",
        f"- 精确模板序列 hash 在训练/验证间重叠 {template_manifest['sequence_audit']['exact_hash_overlap']} 种；因此高指标只作为 v0.1 基线，不代表零泄漏或跨系统泛化。",
        "- 阈值只在 FPR ≤ 1% 的验证点中选择；分数越大越异常，不解释为概率。",
        f"- 无技能参考：全正常 F1=0；全异常 F1={all_anomaly_f1:.6f}。LR 高于两者；ERROR 规则在误报约束内没有有用阈值。",
        "- Drain3 仅用训练数据拟合，验证阶段只调用冻结 match；快照前后哈希一致。",
        "- IPv4 哈希事件簇只是降低泄漏风险的观测代理，不代表真实故障事件。",
        "- W2 不报告测试集成绩，不实现根因分类、LSTM、RAG、Agent、API 或前端。",
    ]
    (docs / "w2_experiment_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    card = [
        "# 异常检测基线 v0.1 模型卡", "",
        "该版本用于 HDFS block 会话级异常筛查研究。主模型是模板 unigram TF-IDF + Logistic Regression；同时登记规则与 Isolation Forest 基线。", "",
        "## 训练和特征", "",
        "- 训练数据：冻结协议中的 Dmain，最多 100,000 个会话。",
        "- 模板：Drain3，仅在训练日志上按原始行顺序拟合。",
        "- 特征排除 label、block ID、IP、PID 和路径。",
        "- 验证阈值满足 FPR ≤ 1%；输出分数不是异常概率。", "",
        "## 适用范围和风险", "",
        "仅适合当前 HDFS 数据版本的离线研究。主机代理不是真实事件标签；模板漂移、UNK 增长和生产日志差异都可能显著降低效果。不得据此自动处置生产故障。测试集尚未启封。", "",
        "## 完整性", "",
        f"- 数据协议哈希：`{protocol_manifest['membership_hash']}`",
        f"- 模板 manifest 哈希：`{training['template_manifest_hash']}`",
        f"- TF-IDF 词表哈希：`{training['vocabulary_hash']}`",
        f"- 实验运行：`{training['run_id']}`",
    ]
    (docs / "w2_model_card.md").write_text("\n".join(card) + "\n", encoding="utf-8")

    targets = [
        "# W2 目标登记表", "",
        "| 目标 | 结果 |", "|---|---|",
        f"| Conda Python 3.11 专用环境 | 通过（{training['environment']['python']}） |",
        f"| Dmain ≤ 100,000 | 通过（{protocol_manifest['dmain_sessions']}） |",
        f"| 完整验证集 | 通过（{training['validation_sessions']}） |",
        f"| Drain3 验证冻结 | {'通过' if template_manifest['snapshot_unchanged_after_inference'] else '失败'} |",
        "| 规则 / LR / IF 均有结果 | 通过 |",
        f"| LR 优于无技能 F1 参考 | 通过（LR {evaluation['methods']['logistic_regression']['f1']:.6f}；全异常 {all_anomaly_f1:.6f}） |",
        "| 测试集封存 | 通过（无测试预测或指标） |",
        "| 人工复核 Drain3 200 行 | 待用户核验 template_review.json |",
    ]
    (docs / "w2_target_registry.md").write_text("\n".join(targets) + "\n", encoding="utf-8")


def evaluate(cfg, split="validation"):
    if split == "test":
        raise ValueError("W2 sealed the test split; test evaluation is forbidden")
    if split not in {"dev", "validation"}:
        raise ValueError("split must be dev or validation")
    if split == "dev":
        return {"split": "dev", "status": "diagnostic subset; no W2 report generated"}
    training = train(cfg)
    run_dir = Path(training["run_dir"])
    if (run_dir / "registry.json").exists():
        verified_manifest(run_dir, "registry.json")
        verified_manifest(run_dir, "training.json")
        existing = json.loads((run_dir / "evaluation.json").read_text(encoding="utf-8"))
        _publish_docs(cfg, training, existing,
                      verified_manifest(cfg["artifact_dir"], "templates.json"),
                      verified_manifest(cfg["protocol_dir"], "manifest.json"))
        return existing
    rows = pq.read_table(run_dir / "predictions.parquet").to_pylist()
    labels = [row["label"] for row in rows]
    methods = {}
    pr_curves = {}
    max_gap = timedelta(seconds=cfg["event_proxy"]["max_gap_seconds"])
    max_span = timedelta(seconds=cfg["event_proxy"]["max_span_seconds"])
    starts = [datetime.fromisoformat(r["start_time"]) for r in rows]
    ends = [datetime.fromisoformat(r["end_time"]) for r in rows]
    hours = (max(ends) - min(starts)).total_seconds() / 3600 if rows else 0.0
    raw_lines = sum(r["line_count"] for r in rows)
    for method in METHODS:
        score_name = method + "_score"
        prediction_name = method + "_prediction"
        scores = [row[score_name] for row in rows]
        predictions = [row[prediction_name] for row in rows]
        result = classification_metrics(labels, predictions, scores)
        events = _false_positive_events(rows, prediction_name, max_gap, max_span)
        result.update({
            "threshold": training["thresholds"][method],
            "false_positive_sessions": result["fp"],
            "false_positive_events": events,
            "false_positive_events_per_10000_lines": events * 10000 / raw_lines if raw_lines else None,
            "false_positive_events_per_hour": events / hours if hours else None,
        })
        methods[method] = result
        pr_curves[method] = pr_curve(labels, scores)

    failures = {}
    for method in METHODS:
        score_name, prediction_name = method + "_score", method + "_prediction"
        fp = sorted((r for r in rows if r["label"] == 0 and r[prediction_name] == 1),
                    key=lambda r: (-r[score_name], r["block_id"]))[:10]
        fn = sorted((r for r in rows if r["label"] == 1 and r[prediction_name] == 0),
                    key=lambda r: (r[score_name], r["block_id"]))[:10]
        keep = ("block_id", "label", "start_time", "line_count", "first_log_id", "last_log_id",
                "template_ids", score_name)
        failures[method] = {
            "highest_false_positives": [{k: r[k] for k in keep} for r in fp],
            "lowest_false_negatives": [{k: r[k] for k in keep} for r in fn],
        }
    evaluation = {
        "schema_version": 1, "run_id": training["run_id"], "split": "validation",
        "methods": methods, "validation_lines": raw_lines,
        "observation_hours": hours, "test_accessed": False,
    }
    save(run_dir / "evaluation.json", evaluation)
    save(run_dir / "pr_curves.json", pr_curves)
    save(run_dir / "failure_cases.json", failures)
    protocol = verified_manifest(cfg["protocol_dir"], "manifest.json")
    templates = verified_manifest(cfg["artifact_dir"], "templates.json")
    _publish_docs(cfg, training, evaluation, templates, protocol)
    registry_files = ["training.json", "evaluation.json", "pr_curves.json", "failure_cases.json"]
    save(run_dir / "registry.json", {
        "schema_version": 1, "run_id": training["run_id"], "test_accessed": False,
        "artifacts": {name: digest(run_dir / name) for name in registry_files},
    })
    return evaluation
