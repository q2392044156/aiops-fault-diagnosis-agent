"""在 WSL 单机 Hadoop 上跑一次卷故障实验（只读 remount）。"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

# ROOT 指向仓库根目录。
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ops" / "lab" / "harness"))

from ingest import ingest_log

from offline.case.lab import build_incident, redact, sha256_text, write_incident

# ENV 是每次 WSL 命令都要带上的 Hadoop 环境。
ENV = ("export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64; "
       "export HADOOP_HOME=/opt/lab/hadoop; export PATH=$HADOOP_HOME/bin:$PATH; ")


# _wsl 在 WSL 里执行一条 root 命令并返回标准输出。
def _wsl(command, check=True):
    value = subprocess.run(["wsl", "-u", "root", "-e", "bash", "-c", ENV + command],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
    if check and value.returncode != 0:
        raise RuntimeError(f"wsl command failed: {value.stderr[-300:]}")
    return value.stdout


# _wait_live 等待 DataNode 重新注册。
def _wait_live(timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if "Live datanodes (1)" in _wsl("hdfs dfsadmin -report 2>&1", check=False):
            return True
        time.sleep(3)
    return False


# run 执行一次只读卷故障实验并产出 incident。
def run(database, require_signal=False, disk_io=False):
    started = datetime.now(UTC)
    prefix = "inc_wsl_disk_io" if disk_io else "inc_wsl_volume"
    case_id = f"{prefix}_{started:%Y%m%d%H%M%S}_{uuid.uuid4().hex[:4]}"
    case_dir = ROOT / "ops" / "lab" / "wsl_cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    def _inject_ro():
        _wsl("/usr/lib/jvm/java-11-openjdk-amd64/bin/jps | awk '/DataNode/{print $1}' | "
             "xargs -r kill -9", check=False)
        for _ in range(15):
            if _wsl("/usr/lib/jvm/java-11-openjdk-amd64/bin/jps | grep -c DataNode",
                    check=False).strip() == "0":
                break
            time.sleep(1)
        _wsl("umount /mnt/labvol 2>/dev/null; umount /mnt/labvol 2>/dev/null; "
             "umount -l /mnt/labvol 2>/dev/null; true", check=False)
        options = _wsl("DEV=$(losetup -j /opt/lab/vol.img | cut -d: -f1); "
                       "if [ -z \"$DEV\" ]; then DEV=$(losetup -f); "
                       "losetup \"$DEV\" /opt/lab/vol.img; fi; "
                       "mount -o ro \"$DEV\" /mnt/labvol 2>/dev/null; "
                       "findmnt -no OPTIONS /mnt/labvol", check=False)
        if "ro" not in options:
            _wsl("mount -o remount,ro /mnt/labvol", check=False)
            options = _wsl("findmnt -no OPTIONS /mnt/labvol", check=False)
        if "ro" not in options:
            return False
        _wsl(": > /opt/lab/dn_ro.log; nohup hdfs datanode > /opt/lab/dn_ro.log "
             "2>&1 & sleep 3")
        time.sleep(2)
        count = _wsl("grep -c 'Too many failed volumes' /opt/lab/dn_ro.log || true",
                     check=False).strip()
        return count not in ("", "0")

    nn_start = int(_wsl("wc -l < /opt/lab/nn.log", check=False).strip() or "0")
    t0 = datetime.now(UTC)
    injection_ok = _inject_ro() or _inject_ro()

    signal_at, found = datetime.now(UTC), False
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        count = _wsl("grep -c 'Too many failed volumes' /opt/lab/dn_ro.log || true",
                     check=False).strip()
        if count and count != "0":
            signal_at, found = datetime.now(UTC), True
            break
        time.sleep(2)

    cutoff = (signal_at + timedelta(seconds=5)) if found else (t0 + timedelta(seconds=45))
    dn_log = _wsl("cat /opt/lab/dn_ro.log 2>/dev/null", check=False)
    nn_log = _wsl(f"tail -n +{nn_start + 1} /opt/lab/nn.log 2>/dev/null", check=False)
    text = "\n".join(f"[aiops-lab-dn1] {line}" for line in dn_log.splitlines())
    text += "\n" + "\n".join(f"[aiops-lab-namenode] {line}"
                             for line in nn_log.splitlines())
    text = redact(text) + "\n"

    metrics = _wsl("df -B1 /mnt/labvol | tail -1", check=False).strip()
    metrics_csv = "timestamp,host_alias,component,metric,value\n"
    if metrics:
        parts = metrics.split()
        if len(parts) >= 4:
            metrics_csv += (f"{cutoff.isoformat()},aiops-lab-dn1,DataNode,"
                            f"disk_avail_bytes,{parts[3]}\n")

    _wsl("umount /mnt/labvol 2>/dev/null || umount -l /mnt/labvol 2>/dev/null || true; "
         "sleep 2; DEV=$(losetup -j /opt/lab/vol.img | cut -d: -f1); "
         "if [ -z \"$DEV\" ]; then DEV=$(losetup -f); "
         "losetup \"$DEV\" /opt/lab/vol.img; fi; "
         "mount -o rw \"$DEV\" /mnt/labvol", check=False)
    _wsl("hdfs --daemon start datanode", check=False)
    live = _wait_live(120)
    if require_signal and not found:
        raise RuntimeError("WSL volume injection signal was not observed")
    recovered = datetime.now(UTC)
    human = recovered + timedelta(seconds=5)

    logs_path = case_dir / "evidence" / "logs" / f"{case_id}.log"
    metrics_path = case_dir / "evidence" / "metrics" / f"{case_id}.csv"
    ticket_path = case_dir / "evidence" / "tickets" / f"{case_id}.md"
    for path in (logs_path, metrics_path, ticket_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    logs_path.write_text(text, encoding="utf-8")
    metrics_path.write_text(metrics_csv, encoding="utf-8")
    ticket_path.write_text("# 值班记录\n\nDataNode 卷异常，按只读流程排查。\n", encoding="utf-8")

    record = build_incident(
        incident_id=case_id, cluster_alias="cluster_wsl",
        fault_code="DISK_IO" if disk_io else "DN_VOLUME",
        fault_family="disk_io" if disk_io else "dn_volume",
        timestamps={"fault_start": t0, "first_observable_signal": signal_at,
                    "agent_detected": None, "human_confirmed": human,
                    "recovered": recovered},
        log_ref={"ref_id": f"log_{case_id}", "content_sha256": sha256_text(text),
                 "redaction_status": "approved_redacted"},
        metric_ref={"ref_id": f"metrics_{case_id}",
                    "content_sha256": sha256_text(metrics_csv),
                    "redaction_status": "approved_redacted"},
        ticket_ref={"ref_id": f"ticket_{case_id}",
                    "content_sha256": sha256_text(ticket_path.read_text(encoding="utf-8")),
                    "redaction_status": "approved_redacted"},
        cutoff_time=cutoff)
    write_incident(case_dir / "incident.json", record)

    from aiops_diag.platform.db import Database
    from offline.case.incident import import_incident
    database_path = database
    database = Database(database_path)
    database.init()
    imported = import_incident(database, case_dir / "incident.json")

    mapping = ingest_log(case_id, logs_path, database_path, t0.isoformat(),
                         signal_at.isoformat(), "template", focus_component="DataNode")
    mapping.update({"fault": "DISK_IO" if disk_io else "DN_VOLUME", "mode": "wsl",
                    "live_recovered": live,
                    "injection_ok": injection_ok, "imported": imported["status"]})
    (case_dir / "map.json").write_text(
        __import__("json").dumps(mapping, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return {"case_id": case_id, "case_dir": str(case_dir), "found": found,
            "recovered": live, "mapping": mapping}


# run_heartbeat 执行一次心跳丢失实验并产出 incident。
def run_heartbeat(database):
    started = datetime.now(UTC)
    case_id = f"inc_wsl_heartbeat_{started:%Y%m%d%H%M%S}_{uuid.uuid4().hex[:4]}"
    case_dir = ROOT / "ops" / "lab" / "wsl_cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    if not _wait_live(30):
        _wsl("hdfs --daemon start datanode", check=False)
        _wait_live(90)
    start_line = int(_wsl("wc -l < /opt/lab/nn.log", check=False).strip() or "0")

    t0 = datetime.now(UTC)
    _wsl("/usr/lib/jvm/java-11-openjdk-amd64/bin/jps | awk '/DataNode/{print $1}' | "
         "xargs -r kill -9", check=False)

    signal_at, found = datetime.now(UTC), False
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        out = _wsl(f"tail -n +{start_line + 1} /opt/lab/nn.log | "
                   "grep -E 'Dead datanode|removeDeadDatanode|is dead' | tail -1",
                   check=False).strip()
        if out:
            signal_at, found = datetime.now(UTC), True
            break
        time.sleep(2)

    cutoff = (signal_at + timedelta(seconds=5)) if found else (t0 + timedelta(seconds=90))
    nn_log = _wsl(f"tail -n +{start_line + 1} /opt/lab/nn.log", check=False)
    dn_log = _wsl("tail -100 /opt/lab/dn.log", check=False)
    text = "\n".join(f"[aiops-lab-namenode] {line}" for line in nn_log.splitlines())
    text += "\n" + "\n".join(f"[aiops-lab-dn1] {line}" for line in dn_log.splitlines())
    text = redact(text) + "\n"

    _wsl("hdfs --daemon start datanode", check=False)
    live = _wait_live(120)
    recovered = datetime.now(UTC)
    human = recovered + timedelta(seconds=5)

    logs_path = case_dir / "evidence" / "logs" / f"{case_id}.log"
    metrics_path = case_dir / "evidence" / "metrics" / f"{case_id}.csv"
    ticket_path = case_dir / "evidence" / "tickets" / f"{case_id}.md"
    for path in (logs_path, metrics_path, ticket_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    logs_path.write_text(text, encoding="utf-8")
    metrics_csv = "timestamp,host_alias,component,metric,value\n"
    metrics_path.write_text(metrics_csv, encoding="utf-8")
    ticket_path.write_text("# 值班记录\n\nDataNode 失联，按只读流程排查。\n", encoding="utf-8")

    record = build_incident(
        incident_id=case_id, cluster_alias="cluster_wsl", fault_code="DN_HEARTBEAT",
        fault_family="dn_heartbeat",
        timestamps={"fault_start": t0, "first_observable_signal": signal_at,
                    "agent_detected": None, "human_confirmed": human,
                    "recovered": recovered},
        log_ref={"ref_id": f"log_{case_id}", "content_sha256": sha256_text(text),
                 "redaction_status": "approved_redacted"},
        metric_ref={"ref_id": f"metrics_{case_id}",
                    "content_sha256": sha256_text(metrics_csv),
                    "redaction_status": "approved_redacted"},
        ticket_ref={"ref_id": f"ticket_{case_id}",
                    "content_sha256": sha256_text(ticket_path.read_text(encoding="utf-8")),
                    "redaction_status": "approved_redacted"},
        cutoff_time=cutoff)
    write_incident(case_dir / "incident.json", record)

    from aiops_diag.platform.db import Database
    from offline.case.incident import import_incident
    database_path = database
    database = Database(database_path)
    database.init()
    imported = import_incident(database, case_dir / "incident.json")

    mapping = ingest_log(case_id, logs_path, database_path, t0.isoformat(),
                         signal_at.isoformat(), "template", focus_component="DataNode")
    mapping.update({"fault": "DN_HEARTBEAT", "mode": "wsl", "live_recovered": live,
                    "imported": imported["status"]})
    (case_dir / "map.json").write_text(
        __import__("json").dumps(mapping, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return {"case_id": case_id, "case_dir": str(case_dir), "found": found,
            "recovered": live, "mapping": mapping}


# run_safemode 执行一次 NameNode 安全模式实验并产出 incident。
def run_safemode(database):
    started = datetime.now(UTC)
    case_id = f"inc_wsl_safe_mode_{started:%Y%m%d%H%M%S}_{uuid.uuid4().hex[:4]}"
    case_dir = ROOT / "ops" / "lab" / "wsl_cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    if not _wait_live(30):
        _wsl("hdfs --daemon start datanode", check=False)
        _wait_live(90)
    _wsl("hdfs dfsadmin -safemode leave", check=False)
    nn_start = int(_wsl("wc -l < /opt/lab/nn.log", check=False).strip() or "0")

    t0 = datetime.now(UTC)
    _wsl("hdfs dfsadmin -safemode enter", check=False)

    signal_at, found = datetime.now(UTC), False
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        count = _wsl(f"tail -n +{nn_start + 1} /opt/lab/nn.log | "
                     "grep -c 'Safe mode is ON' || true", check=False).strip()
        if count and count != "0":
            signal_at, found = datetime.now(UTC), True
            break
        time.sleep(2)

    cutoff = (signal_at + timedelta(seconds=5)) if found else (t0 + timedelta(seconds=30))
    nn_log = _wsl(f"tail -n +{nn_start + 1} /opt/lab/nn.log", check=False)
    text = "\n".join(f"[aiops-lab-namenode] {line}" for line in nn_log.splitlines())
    text = redact(text) + "\n"

    _wsl("hdfs dfsadmin -safemode leave", check=False)
    live = _wait_live(60)
    recovered = datetime.now(UTC)
    human = recovered + timedelta(seconds=5)

    logs_path = case_dir / "evidence" / "logs" / f"{case_id}.log"
    metrics_path = case_dir / "evidence" / "metrics" / f"{case_id}.csv"
    ticket_path = case_dir / "evidence" / "tickets" / f"{case_id}.md"
    for path in (logs_path, metrics_path, ticket_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    logs_path.write_text(text, encoding="utf-8")
    metrics_csv = "timestamp,host_alias,component,metric,value\n"
    metrics_path.write_text(metrics_csv, encoding="utf-8")
    ticket_path.write_text("# 值班记录\n\n集群只读，按只读流程排查。\n", encoding="utf-8")

    record = build_incident(
        incident_id=case_id, cluster_alias="cluster_wsl", fault_code="NN_SAFE_MODE",
        fault_family="nn_safe_mode",
        timestamps={"fault_start": t0, "first_observable_signal": signal_at,
                    "agent_detected": None, "human_confirmed": human,
                    "recovered": recovered},
        log_ref={"ref_id": f"log_{case_id}", "content_sha256": sha256_text(text),
                 "redaction_status": "approved_redacted"},
        metric_ref={"ref_id": f"metrics_{case_id}",
                    "content_sha256": sha256_text(metrics_csv),
                    "redaction_status": "approved_redacted"},
        ticket_ref={"ref_id": f"ticket_{case_id}",
                    "content_sha256": sha256_text(ticket_path.read_text(encoding="utf-8")),
                    "redaction_status": "approved_redacted"},
        cutoff_time=cutoff)
    write_incident(case_dir / "incident.json", record)

    from aiops_diag.platform.db import Database
    from offline.case.incident import import_incident
    database_path = database
    database = Database(database_path)
    database.init()
    imported = import_incident(database, case_dir / "incident.json")

    mapping = ingest_log(case_id, logs_path, database_path, t0.isoformat(),
                         signal_at.isoformat(), "template", focus_component="NameNode")
    mapping.update({"fault": "NN_SAFE_MODE", "mode": "wsl", "live_recovered": live,
                    "imported": imported["status"]})
    (case_dir / "map.json").write_text(
        __import__("json").dumps(mapping, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return {"case_id": case_id, "case_dir": str(case_dir), "found": found,
            "recovered": live, "mapping": mapping}


# main 解析参数并执行实验。
def main(argv=None):
    parser = argparse.ArgumentParser(description="WSL single-node volume experiment")
    parser.add_argument("--database", default=str(ROOT / "runtime/lab/wsl.sqlite3"))
    parser.add_argument("--fault", default="DN_VOLUME",
                        choices=("DN_VOLUME", "DN_HEARTBEAT", "NN_SAFE_MODE", "DISK_IO"))
    parser.add_argument("--require-signal", action="store_true")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.fault == "DN_HEARTBEAT":
        print(run_heartbeat(args.database))
    elif args.fault == "NN_SAFE_MODE":
        print(run_safemode(args.database))
    else:
        print(run(args.database, require_signal=args.require_signal,
                  disk_io=args.fault == "DISK_IO"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
