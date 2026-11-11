"""脚本说明：网络分区与心跳丢失的案例级混淆矩阵。"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

# 变量说明：NETWORK 是网络分区根因码。
NETWORK = "NETWORK_CONNECTIVITY"
# 变量说明：HEARTBEAT 是心跳丢失根因码。
HEARTBEAT = "DN_HEARTBEAT"
# 变量说明：NETWORK_PATTERNS 是网络不通证据词。
NETWORK_PATTERNS = (r"retrying connect", r"connection timed out", r"no route to host",
                    r"network is unreachable", r"connection reset")
# 变量说明：DEATH_PATTERNS 是进程死亡证据词。
DEATH_PATTERNS = (r"lost datanode", r"dead datanode", r"exiting datanode", r"removedead")


# 方法说明：_incident 读取案例真实根因。
def _incident(case):
    return json.loads((Path(case) / "incident.json").read_text(encoding="utf-8"))


# 方法说明：_predict 读取案例所有 event 的首选根因。
def _predict(gate, db):
    codes = []
    for event in gate.get("events", []):
        row = db.execute("SELECT report_json FROM incident_reports WHERE report_id=?",
                         (event.get("report_id"),)).fetchone()
        if not row:
            continue
        hypotheses = json.loads(row[0]).get("hypotheses", [])
        code = hypotheses[0].get("root_cause_code") if hypotheses else None
        if code:
            codes.append(code)
    if not codes:
        return None
    return Counter(codes).most_common(1)[0][0]


# 方法说明：_features 统计案例日志里的网络/死亡证据词。
def _features(case):
    text = " ".join(path.read_text(encoding="utf-8", errors="ignore")
                    for path in (Path(case) / "evidence" / "logs").glob("*.log")).lower()
    network = sum(bool(re.search(pattern, text)) for pattern in NETWORK_PATTERNS)
    death = sum(bool(re.search(pattern, text)) for pattern in DEATH_PATTERNS)
    return {"network_signal_types": network, "death_signal_types": death}


# 方法说明：main 输出 2x2 矩阵与误分类案例。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--network-gates", required=True)
    parser.add_argument("--network-db", required=True)
    parser.add_argument("--network-cases", required=True)
    parser.add_argument("--heartbeat-gates", required=True)
    parser.add_argument("--heartbeat-db", required=True)
    parser.add_argument("--heartbeat-cases", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    network_gates = json.loads(Path(args.network_gates).read_text(encoding="utf-8"))
    heartbeat_gates = json.loads(Path(args.heartbeat_gates).read_text(encoding="utf-8"))
    n_db = sqlite3.connect(args.network_db)
    h_db = sqlite3.connect(args.heartbeat_db)
    rows = []
    for gate in network_gates:
        case = Path(args.network_cases) / gate["incident_id"]
        if not (case / "incident.json").is_file():
            continue
        rows.append({"case": gate["incident_id"], "true": NETWORK,
                     "pred": _predict(gate, n_db), **_features(case)})
    for gate in heartbeat_gates:
        case = Path(args.heartbeat_cases) / gate["incident_id"]
        if not (case / "incident.json").is_file():
            continue
        incident = _incident(case)
        if incident["labels"]["root_cause_code"] != HEARTBEAT:
            continue
        rows.append({"case": gate["incident_id"], "true": HEARTBEAT,
                     "pred": _predict(gate, h_db), **_features(case)})
    matrix = {true: {pred: 0 for pred in (NETWORK, HEARTBEAT, None)}
              for true in (NETWORK, HEARTBEAT)}
    for row in rows:
        matrix[row["true"]][row["pred"]] += 1
    # 方法说明：metrics 计算单个类别的 precision/recall。
    def metrics(label):
        tp = matrix[label][label]
        fn = sum(matrix[label][other] for other in matrix[label] if other != label)
        fp = sum(matrix[other][label] for other in matrix if other != label)
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        return {"precision": round(precision, 4) if precision is not None else None,
                "recall": round(recall, 4) if recall is not None else None}
    payload = {"rows": rows, "matrix": matrix,
               "network": metrics(NETWORK), "heartbeat": metrics(HEARTBEAT),
               "misclassified": [row for row in rows if row["pred"] != row["true"]]}
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps({"matrix": matrix, "network": payload["network"],
                      "heartbeat": payload["heartbeat"],
                      "misclassified": len(payload["misclassified"])},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
