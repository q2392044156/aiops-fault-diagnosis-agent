"""模块说明：编排一次受控故障实验，产出 incident.json 与附带映射。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 变量说明：ROOT 指向仓库根目录。
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from aiops_diag.data.lab import build_incident, redact, sha256_text, write_incident

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest import ingest_log

# 变量说明：COMPOSE 是本机实验台的 compose 文件。
COMPOSE = ROOT / "ops" / "lab" / "compose.yaml"

# 变量说明：FAULTS 定义三个 MVP 故障族的注入与恢复方式。
FAULTS = {
    "DN_VOLUME": {
        "component": "DataNode", "container": "aiops-lab-dn1", "mode": "exec",
        "signal": r"No space left on device|Volume .* failed|failed volume",
        "inject": "dn_volume_full.sh", "recover": "dn_volume_recover.sh",
        "dry": ["WARN dfs.FSDataset: Volume /data/1 failed, 0 bytes available",
                "ERROR dfs.DataNode$DataXceiver: writeBlock received exception "
                "java.io.IOException: No space left on device"],
    },
    "DN_HEARTBEAT": {
        "component": "DataNode", "container": "aiops-lab-dn2", "mode": "kill",
        "signal": r"Lost DataNode|dead datanode|Dead datanode|is dead|heartbeat",
        "signal_container": "aiops-lab-namenode", "min_observe": 40,
        "inject": None, "recover": None,
        "dry": ["WARN dfs.FSNamesystem: Lost DataNode datanode2",
                "INFO dfs.FSNamesystem: BLOCK* ask datanode2 to replicate"],
    },
    "NN_SAFE_MODE": {
        "component": "NameNode", "container": "aiops-lab-namenode", "mode": "exec",
        "signal": r"Safe mode is ON|safemode|Safe mode",
        "inject": "nn_safemode_enter.sh", "recover": "nn_safemode_leave.sh",
        "dry": ["INFO dfs.FSNamesystem: Entering safe mode",
                "WARN dfs.FSNamesystem: Safe mode is ON. The reported blocks needs "
                "additional blocks to reach the threshold"],
    },
}


# 方法说明：_docker 执行一条 docker 命令并返回标准输出。
def _docker(*args, check=True):
    value = subprocess.run(["docker", *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    if check and value.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} failed: {value.stderr[-400:]}")
    return value.stdout


# 方法说明：_wait_ready 等待 NameNode 报告 3 个活跃 DataNode。
def _wait_ready(timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        output = _docker("exec", "aiops-lab-namenode", "hdfs", "dfsadmin", "-report",
                         check=False)
        if re.search(r"Live datanodes \(3\)", output):
            return True
        time.sleep(5)
    return False


# 方法说明：_capture_logs 采集时间窗内的容器日志并脱敏合并。
def _capture_logs(containers, since, until):
    chunks = []
    for name in containers:
        text = _docker("logs", "--since", since, "--until", until, name, check=False)
        if not text.strip():
            text = _docker("logs", "--until", until, "--tail", "20", name, check=False)
        for line in text.splitlines():
            chunks.append(f"[{name}] {line}")
    return redact("\n".join(chunks)) + "\n"


# 方法说明：_metrics 采样一次容器资源占用，写成指标 CSV。
def _metrics(containers):
    rows = ["timestamp,host_alias,component,metric,value"]
    stamp = datetime.now(timezone.utc).isoformat()
    for name in containers:
        output = _docker("stats", "--no-stream", "--format", "{{json .}}", name, check=False)
        try:
            item = json.loads(output.strip().splitlines()[-1])
        except (ValueError, IndexError):
            continue
        cpu = float(str(item.get("CPUPerc", "0%")).rstrip("%") or 0)
        memory = str(item.get("MemUsage", "0MiB / 0MiB")).split("/")[0].strip()
        match = re.match(r"([\d.]+)([KMGT]?i?B)", memory)
        value = float(match.group(1)) if match else 0.0
        if match and match.group(2).startswith("G"):
            value *= 1024
        component = "NameNode" if "namenode" in name else "DataNode"
        rows.append(f"{stamp},{name},{component},cpu_percent,{cpu}")
        rows.append(f"{stamp},{name},{component},mem_mib,{value}")
    return "\n".join(rows) + "\n"


# 方法说明：_wait_signal 轮询日志，返回首次可观测信号时间。
def _wait_signal(spec, since, timeout):
    deadline = time.monotonic() + timeout
    pattern = re.compile(spec["signal"], re.I)
    target = spec.get("signal_container", spec["container"])
    while time.monotonic() < deadline:
        text = _docker("logs", "--since", since, target, check=False)
        if pattern.search(text):
            return datetime.now(timezone.utc)
        time.sleep(3)
    return datetime.now(timezone.utc)


# 方法说明：_dry 生成一份与真实故障同形的离线样本，用于无集群时验证链路。
def _dry(fault, start):
    spec = FAULTS[fault]
    host = spec["container"]
    lines = []
    for index in range(10):
        stamp = (start + timedelta(seconds=index)).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"[{host}] {stamp} INFO  lab.Workload: case {start.isoformat()} "
                     f"normal workload line {index}")
    for offset, item in enumerate(spec["dry"], 1):
        level, _, message = item.partition(" ")
        stamp = (start + timedelta(seconds=20 + offset)).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"[{host}] {stamp} {level}  lab.Fault: {message}")
    metrics = ["timestamp,host_alias,component,metric,value"]
    for offset in range(0, 60, 10):
        stamp = (start + timedelta(seconds=offset)).isoformat()
        value = 0.2 if offset < 20 else 0.99 if offset < 50 else 0.3
        metrics.append(f"{stamp},{spec['container']},{spec['component']},"
                       f"disk_used_ratio,{value}")
    return "\n".join(lines) + "\n", "\n".join(metrics) + "\n"


# 方法说明：run_case 执行一次实验并写出 incident 与映射文件。
def run_case(fault, observe_seconds=60, dry_run=False, import_db=None, case_root=None,
             ingest_db=None):
    spec = FAULTS[fault]
    started = datetime.now(timezone.utc)
    case_id = f"inc_lab_{fault.lower()}_{started:%Y%m%d%H%M%S}_{uuid.uuid4().hex[:4]}"
    case_dir = Path(case_root or ROOT / "ops" / "lab" / "cases") / case_id
    if dry_run:
        t0 = started - timedelta(seconds=120)
        signal_at = t0 + timedelta(seconds=20)
        cutoff = t0 + timedelta(seconds=observe_seconds)
        recovered = cutoff + timedelta(seconds=30)
        human = recovered + timedelta(seconds=10)
        logs, metrics = _dry(fault, t0)
        agent_detected = None
    else:
        _docker("compose", "-f", str(COMPOSE), "up", "-d")
        if not _wait_ready(180):
            raise RuntimeError("HDFS cluster did not become ready")
        t0 = datetime.now(timezone.utc)
        if spec["mode"] == "kill":
            _docker("kill", spec["container"])
        else:
            _docker("exec", spec["container"], "bash", f"/lab/inject/{spec['inject']}",
                    check=False)
        window_seconds = max(observe_seconds, int(spec.get("min_observe", 0)))
        signal_at = _wait_signal(spec, t0.isoformat(), window_seconds)
        window_end = t0 + timedelta(seconds=window_seconds)
        remaining = (window_end - datetime.now(timezone.utc)).total_seconds()
        if remaining > 0:
            time.sleep(remaining)
        cutoff = window_end
        logs = _capture_logs(sorted({spec["container"], "aiops-lab-namenode"}),
                              t0.isoformat(), cutoff.isoformat())
        metrics = _metrics(["aiops-lab-namenode", "aiops-lab-dn1", "aiops-lab-dn2",
                            "aiops-lab-dn3"])
        if spec["mode"] == "kill":
            _docker("start", spec["container"])
        else:
            _docker("exec", spec["container"], "bash", f"/lab/inject/{spec['recover']}",
                    check=False)
            if fault == "DN_VOLUME":
                time.sleep(2)
                _docker("restart", spec["container"])
        _wait_ready(180)
        recovered = datetime.now(timezone.utc)
        human = recovered + timedelta(seconds=10)
        agent_detected = None

    logs = redact(logs)
    logs_path = case_dir / "evidence" / "logs" / f"{case_id}.log"
    metrics_path = case_dir / "evidence" / "metrics" / f"{case_id}.csv"
    ticket_path = case_dir / "evidence" / "tickets" / f"{case_id}.md"
    logs_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    ticket_path.parent.mkdir(parents=True, exist_ok=True)
    logs_path.write_text(logs, encoding="utf-8")
    metrics_path.write_text(metrics, encoding="utf-8")
    ticket_path.write_text("# 值班记录\n\n集群写入变慢，按只读流程排查。\n", encoding="utf-8")

    ingest_mapping = None
    if ingest_db:
        ingest_mapping = ingest_log(case_id, logs_path, ingest_db, t0.isoformat(),
                                    signal_at.isoformat(), "template",
                                    focus_component=spec["component"])
        agent_detected = datetime.fromisoformat(ingest_mapping["agent_detected"])

    record = build_incident(
        incident_id=case_id, cluster_alias="cluster_lab_a1", fault_code=fault,
        fault_family=fault.lower(),
        timestamps={"fault_start": t0, "first_observable_signal": signal_at,
                    "agent_detected": agent_detected, "human_confirmed": human,
                    "recovered": recovered},
        log_ref={"ref_id": f"log_{case_id}", "content_sha256": sha256_text(logs),
                 "redaction_status": "approved_redacted"},
        metric_ref={"ref_id": f"metrics_{case_id}", "content_sha256": sha256_text(metrics),
                    "redaction_status": "approved_redacted"},
        ticket_ref={"ref_id": f"ticket_{case_id}", "content_sha256": sha256_text(
            ticket_path.read_text(encoding="utf-8")),
            "redaction_status": "approved_redacted"},
        cutoff_time=cutoff)
    write_incident(case_dir / "incident.json", record)
    mapping = {"incident_id": case_id, "fault": fault, "batch_id": None,
               "event_id": None, "diagnosis_id": None, "report_id": None,
               "cutoff_time": cutoff.isoformat(),
               "mode": "ingest" if ingest_mapping else ("dry-run" if dry_run else "cluster")}
    if ingest_mapping:
        mapping.update({name: ingest_mapping.get(name) for name in (
            "batch_id", "event_id", "diagnosis_id", "report_id", "agent_detected")})
    (case_dir / "map.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2)
                                       + "\n", encoding="utf-8")

    if import_db:
        from aiops_diag.platform.db import Database
        from aiops_diag.data.incident_v12 import import_incident
        database = Database(import_db)
        database.init()
        value = import_incident(database, case_dir / "incident.json")
        mapping["import"] = value
        (case_dir / "map.json").write_text(json.dumps(mapping, ensure_ascii=False,
                                                     indent=2) + "\n", encoding="utf-8")
    return {"case_dir": str(case_dir), "incident_id": case_id, "fault": fault,
            "dry_run": dry_run}


# 方法说明：main 解析参数并执行一次实验。
def main(argv=None):
    parser = argparse.ArgumentParser(description="Route A lab harness")
    parser.add_argument("--fault", required=True, choices=sorted(FAULTS))
    parser.add_argument("--observe", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--import-db")
    parser.add_argument("--ingest-db")
    parser.add_argument("--case-root")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(run_case(args.fault, args.observe, args.dry_run, args.import_db,
                             args.case_root, args.ingest_db),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
