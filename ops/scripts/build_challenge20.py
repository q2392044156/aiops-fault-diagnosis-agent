"""脚本说明：从 20 个未参与统一评测的实验室案例构造受控分布偏移挑战集。

挑战集不是新的自然采集数据，而是对独立 holdout 案例做四类可控变换：
跨格式/时间（Docker 文本重渲染为 WSL + 时间平移 + 主机改名）、删减正常行、
故障语义同义改写、以及同义改写叠加另一类故障的干扰信号。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 变量说明：ROOT 是仓库根目录。
ROOT = Path(__file__).resolve().parents[2]
# 变量说明：SOURCE 是未进入 unified4 的早期自然 holdout 案例。
SOURCE = ROOT / "ops" / "lab" / "cases"
# 变量说明：OUTPUT 是挑战案例默认输出目录。
OUTPUT = ROOT / "resources" / "evaluation" / "challenge20" / "cases"
# 变量说明：MANIFEST 是挑战集清单默认路径。
MANIFEST = ROOT / "resources" / "evaluation" / "challenge20" / "manifest.json"
# 变量说明：SHIFT 把所有案例时间平移 30 天，避免与训练/测试同时间。
SHIFT = timedelta(days=-30)
# 变量说明：HOSTS 是主机别名映射，模拟生产主机命名。
HOSTS = {
    "aiops-lab-dn1": "prod-datanode-07",
    "aiops-lab-dn2": "prod-datanode-08",
    "aiops-lab-dn3": "prod-datanode-09",
    "aiops-lab-namenode": "prod-namenode-01",
}
# 变量说明：TEXT_HOSTS 是日志正文中的短主机名映射。
TEXT_HOSTS = {
    "datanode1": "prod-datanode-07",
    "datanode2": "prod-datanode-08",
    "datanode3": "prod-datanode-09",
    "namenode": "prod-namenode-01",
}
# 变量说明：LINE 匹配统一的 [host] timestamp level message 行。
LINE = re.compile(
    r"^\[(?P<host>[^\]]+)\]\s+(?P<stamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}"
    r"(?:[.,]\d+)?)\s+(?P<level>[A-Z]+)\s+(?P<rest>.*)$")
# 变量说明：EMBEDDED_ISO 匹配日志正文中的 ISO 时间，需与文件时间一起平移。
EMBEDDED_ISO = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")


# 方法说明：shift_iso 平移 ISO 时间并保持 UTC Z 表示。
def shift_iso(text: str) -> str:
    value = datetime.fromisoformat(text.replace("Z", "+00:00")) + SHIFT
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# 方法说明：sha 计算文件内容哈希，用于更新证据包引用。
def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# 方法说明：rename 同时替换主机别名和日志正文短主机名。
def rename(text: str) -> str:
    for old, new in HOSTS.items():
        text = text.replace(old, new)
    for old, new in TEXT_HOSTS.items():
        text = re.sub(rf"(?<![A-Za-z0-9_-]){old}(?![A-Za-z0-9_-])", new, text)
    return text


# 方法说明：shift_embedded 同步平移日志正文中的 ISO 时间，避免内外时间矛盾。
def shift_embedded(text: str) -> str:
    return EMBEDDED_ISO.sub(lambda match: shift_iso(match.group(0)), text)


# 方法说明：format_wsl 输出带 +08 本地时间的 WSL 日志时间戳。
def format_wsl(stamp: datetime) -> str:
    local = stamp.astimezone(timezone.utc) + timedelta(hours=8)
    return local.strftime("%Y-%m-%d %H:%M:%S,%f")[:23]


# 方法说明：paraphrase 用未见过的同义表述替换四类故障的关键信号。
def paraphrase(rest: str) -> str:
    rest = re.sub(r"Lost DataNode (\S+)", r"DataNode \1 missed its liveness deadline", rest)
    rest = re.sub(r"BLOCK\* ask (\S+) to replicate",
                  r"BLOCK* schedule replication for \1", rest)
    rest = rest.replace("Volume /data/1 failed, 0 bytes available",
                        "Storage volume /data/1 is full (0 bytes free)")
    rest = rest.replace("No space left on device",
                        "ENOSPC while allocating a new block")
    rest = rest.replace("Entering safe mode", "Entering maintenance mode")
    rest = rest.replace("Safe mode is ON.", "Startup guard is active.")
    return rest


# 方法说明：transform_logs 按组重渲染日志；evidence_drop 只保留故障相关行。
def transform_logs(lines: list[str], group: str) -> list[str]:
    out = []
    for line in lines:
        match = LINE.match(line)
        if not match:
            out.append(rename(line))
            continue
        stamp = datetime.fromisoformat(
            match.group("stamp").replace(",", ".")).replace(tzinfo=timezone.utc) + SHIFT
        rest = shift_embedded(rename(match.group("rest")))
        if group.startswith("paraphrase"):
            rest = paraphrase(rest)
        level = match.group("level")
        host = HOSTS.get(match.group("host"), match.group("host"))
        if group == "evidence_drop" and "lab.Fault" not in rest and level not in (
                "ERROR", "WARN", "FATAL"):
            continue
        out.append(f"[{host}] {format_wsl(stamp)} {level}  {rest}")
    return out


# 方法说明：distractor_lines 在故障前插入另一类故障的已知信号。
def distractor_lines(code: str, fault_start: datetime) -> list[str]:
    stamp = fault_start - timedelta(seconds=8)
    if code == "DN_VOLUME":
        host, msg = "prod-namenode-01", "dfs.FSNamesystem: Lost DataNode prod-datanode-08"
        msg2 = "dfs.FSNamesystem: BLOCK* ask prod-datanode-08 to replicate"
    elif code == "DN_HEARTBEAT":
        host, msg = "prod-datanode-07", "dfs.FSDataset: Volume /data/2 failed, 0 bytes available"
        msg2 = "dfs.DataNode: slow volume detection on /data/2"
    else:
        host, msg = "prod-namenode-01", "dfs.FSNamesystem: Lost DataNode prod-datanode-08"
        msg2 = "dfs.FSNamesystem: BLOCK* ask prod-datanode-08 to replicate"
    return [
        f"[{host}] {format_wsl(stamp)} WARN  lab.Fault: {msg}",
        f"[{host}] {format_wsl(stamp + timedelta(seconds=1))} INFO  lab.Fault: {msg2}",
    ]


# 方法说明：shift_incident 重写 incident 的时间、引用和授权信息。
def shift_incident(data: dict, case_id: str, original: str, group: str) -> dict:
    data["incident_id"] = case_id
    data["cluster_alias"] = "cluster_challenge"
    data["authorization"]["authorization_id"] = "auth_challenge_001"
    data["authorization"]["approved_at"] = shift_iso(data["authorization"]["approved_at"])
    data["authorization"]["retention_until"] = shift_iso(data["authorization"]["retention_until"])
    for key in ("fault_start", "first_observable_signal", "agent_detected",
                "human_confirmed", "recovered"):
        data["timestamps"][key] = shift_iso(data["timestamps"][key])
    snap = data["diagnosis_snapshot"]
    snap["cutoff_time"] = shift_iso(snap["cutoff_time"])
    data["labels"]["creator_id"] = "challenge-builder"
    for ref in snap["log_refs"] + snap["metric_refs"] + snap["ticket_refs"]:
        ref["observed_at"] = shift_iso(ref["observed_at"])
        ref["ref_id"] = ref["ref_id"].replace(original, case_id)
    data["labels"]["evidence_refs"] = [
        item.replace(original, case_id) for item in data["labels"]["evidence_refs"]]
    if group.endswith("distractor"):
        start = datetime.fromisoformat(
            data["timestamps"]["fault_start"].replace("Z", "+00:00"))
        early = (start + timedelta(seconds=-8)).astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z")
        data["timestamps"]["first_observable_signal"] = early
    return data


# 方法说明：build_case 复制一个源案例并施加指定扰动。
def build_case(source: Path, case_id: str, group: str, output: Path) -> dict:
    original = source.name
    source_incident = json.loads((source / "incident.json").read_text(encoding="utf-8"))
    code = source_incident["labels"]["root_cause_code"]
    family = {"DN_VOLUME": "volume", "DN_HEARTBEAT": "heartbeat",
              "NN_SAFE_MODE": "safe_mode"}[code]
    target = output / case_id
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    shutil.copytree(source / "evidence", target / "evidence")
    data = json.loads((source / "incident.json").read_text(encoding="utf-8"))
    fault_start = datetime.fromisoformat(
        data["timestamps"]["fault_start"].replace("Z", "+00:00"))
    log_path = sorted((target / "evidence" / "logs").glob("*"))[0]
    source_log_sha = sha(log_path)
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    transformed = transform_logs(lines, group)
    if group.endswith("distractor"):
        transformed = distractor_lines(code, fault_start + SHIFT) + transformed
    log_path.write_text("\n".join(transformed) + "\n", encoding="utf-8")
    data = shift_incident(data, case_id, original, group)
    metric_path = sorted((target / "evidence" / "metrics").glob("*"))[0]
    with metric_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    with metric_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            row["timestamp"] = shift_iso(row["timestamp"])
            row["host_alias"] = HOSTS.get(row["host_alias"], row["host_alias"])
            writer.writerow(row)
    for ticket in (target / "evidence" / "tickets").glob("*"):
        ticket.write_text(rename(ticket.read_text(encoding="utf-8", errors="replace")),
                          encoding="utf-8")
    data["diagnosis_snapshot"]["log_refs"][0]["content_sha256"] = sha(log_path)
    data["diagnosis_snapshot"]["metric_refs"][0]["content_sha256"] = sha(metric_path)
    tickets = sorted((target / "evidence" / "tickets").glob("*"))
    if tickets:
        data["diagnosis_snapshot"]["ticket_refs"][0]["content_sha256"] = sha(tickets[0])
    (target / "incident.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (target / "challenge.json").write_text(json.dumps({
        "synthetic": True,
        "not_independent": True,
        "group": group,
        "original_case": original,
        "source_format": "docker_container->wsl",
        "time_shift_days": -30,
        "host_rename": HOSTS,
        "source_log_sha256": source_log_sha,
        "label_source": "original incident labels",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"case_id": case_id, "path": str(target.relative_to(ROOT)).replace("\\", "/"),
            "batch": "challenge20", "source": "wsl", "root_cause_code": code,
            "family": family, "group": group, "original_case": original,
            "source_format": "docker_container->wsl", "time_shift_days": -30}


# 方法说明：main 选择 20 个独立 holdout 案例并按固定计划分组构造。
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(SOURCE))
    parser.add_argument("--output", default=str(OUTPUT))
    parser.add_argument("--manifest", default=str(MANIFEST))
    args = parser.parse_args()
    source_root = Path(args.source)
    output = Path(args.output)
    by_family = {"volume": [], "heartbeat": [], "safe_mode": []}
    for path in sorted(source_root.iterdir()):
        if not path.is_dir() or not (path / "incident.json").is_file():
            continue
        code = json.loads((path / "incident.json").read_text(
            encoding="utf-8"))["labels"]["root_cause_code"]
        family = {"DN_VOLUME": "volume", "DN_HEARTBEAT": "heartbeat",
                  "NN_SAFE_MODE": "safe_mode"}[code]
        logs = list((path / "evidence" / "logs").glob("*"))
        if family == "safe_mode" and logs:
            if sum(1 for _ in logs[0].open(encoding="utf-8", errors="replace")) < 6:
                continue
        by_family[family].append(path)
    plan = {
        "volume": ["format_time", "format_time", "evidence_drop", "evidence_drop",
                   "paraphrase", "paraphrase", "paraphrase_distractor"],
        "heartbeat": ["format_time", "format_time", "evidence_drop",
                      "paraphrase", "paraphrase", "paraphrase_distractor",
                      "paraphrase_distractor"],
        "safe_mode": ["format_time", "evidence_drop", "evidence_drop",
                      "paraphrase", "paraphrase_distractor",
                      "paraphrase_distractor"],
    }
    cases = []
    index = 0
    for family, groups in plan.items():
        for source, group in zip(by_family[family], groups):
            index += 1
            original = source.name
            case_id = f"inc_chal_{family}_{index:02d}_{original.split('_')[-1]}"
            cases.append(build_case(source, case_id, group, output))
    manifest = {
        "dataset": "challenge20_controlled_shift",
        "synthetic": True,
        "not_independent": True,
        "case_count": len(cases),
        "groups": {name: sum(1 for c in cases if c["group"] == name)
                   for name in ("format_time", "evidence_drop", "paraphrase",
                                "paraphrase_distractor")},
        "classes": {name: sum(1 for c in cases if c["family"] == name)
                    for name in ("volume", "heartbeat", "safe_mode")},
        "holdout_source": "ops/lab/cases (20 independent early lab cases)",
        "cases": cases,
    }
    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    print(json.dumps(manifest["groups"], ensure_ascii=False), manifest["classes"])


if __name__ == "__main__":
    main()
