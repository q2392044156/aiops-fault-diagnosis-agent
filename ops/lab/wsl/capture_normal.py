"""脚本说明：采集 WSL 单机 HDFS 的稳态正常日志。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# 方法说明：_wsl 在 WSL 内执行命令。
def _wsl(distro, command, timeout=60):
    return subprocess.run(["wsl", "-d", distro, "-u", "root", "--", "bash", "-lc", command],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


# 方法说明：_count 返回 WSL 文件当前行数。
def _count(distro, path):
    result = _wsl(distro, f"wc -l < {path}")
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


# 方法说明：main 运行健康读写并采集 NameNode/DataNode 日志。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=5)
    parser.add_argument("--output", required=True)
    parser.add_argument("--distro", default="Ubuntu-24.04")
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--nn-log", default="/opt/lab/nn.log")
    parser.add_argument("--dn-log", default="/opt/lab/dn.log")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    output = Path(args.output)
    (output / "logs").mkdir(parents=True, exist_ok=True)
    nn_start = _count(args.distro, args.nn_log)
    dn_start = _count(args.distro, args.dn_log)
    started = datetime.now(timezone.utc)
    deadline = started.timestamp() + args.minutes * 60
    rounds = 0
    while time.time() < deadline:
        command = (
            "echo normal-$(date +%s) > /tmp/normal.txt; "
            "JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64 /opt/lab/hadoop/bin/hdfs "
            "dfs -mkdir -p /aiops-normal; "
            "JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64 /opt/lab/hadoop/bin/hdfs "
            "dfs -put -f /tmp/normal.txt /aiops-normal/normal.txt; "
            "JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64 /opt/lab/hadoop/bin/hdfs "
            "dfs -ls /aiops-normal >/dev/null")
        result = _wsl(args.distro, command)
        if result.returncode != 0:
            print("workload failed", result.returncode, repr(result.stderr[-300:]),
                  flush=True)
            break
        rounds += 1
        time.sleep(max(0.5, args.interval))
    for name, path, start, host in (("nn.log", args.nn_log, nn_start,
                                      "aiops-lab-namenode"),
                                     ("dn.log", args.dn_log, dn_start, "aiops-lab-dn1")):
        result = _wsl(args.distro, f"tail -n +{start + 1} {path}")
        text = "".join(f"[{host}] {line}\n" for line in result.stdout.splitlines())
        (output / "logs" / name).write_text(text, encoding="utf-8")
    meta = {"schema_version": 1, "source_type": "wsl",
            "started_at": started.isoformat(), "duration_minutes": args.minutes,
            "rounds": rounds, "logs": ["nn.log", "dn.log"]}
    (output / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
