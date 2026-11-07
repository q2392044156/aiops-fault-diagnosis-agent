"""脚本说明：在健康 HDFS 集群上采集稳态正常日志。"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

CONTAINERS = ("aiops-lab-namenode", "aiops-lab-dn1", "aiops-lab-dn2", "aiops-lab-dn3")


# 方法说明：_run 执行 docker 命令并返回输出。
def _run(args, timeout=60):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


# 方法说明：main 运行健康读写负载并采集容器日志。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=5)
    parser.add_argument("--output", required=True)
    parser.add_argument("--interval", type=float, default=5)
    args = parser.parse_args(argv)
    output = Path(args.output)
    (output / "logs").mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    deadline = started.timestamp() + args.minutes * 60
    rounds = 0
    while time.time() < deadline:
        command = (
            "set -e; echo normal-$(date +%s) > /tmp/normal.txt; "
            "hdfs dfs -mkdir -p /aiops-normal; "
            "hdfs dfs -put -f /tmp/normal.txt /aiops-normal/normal.txt; "
            "hdfs dfs -ls /aiops-normal >/dev/null; "
            "hdfs dfs -cat /aiops-normal/normal.txt >/dev/null")
        result = _run(["docker", "exec", "aiops-lab-namenode", "bash", "-lc", command], 60)
        if result.returncode != 0:
            print("workload failed", result.stderr[-300:], flush=True)
            break
        rounds += 1
        time.sleep(max(0.5, args.interval))
    since = started.strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = {}
    for name in CONTAINERS:
        result = _run(["docker", "logs", "--since", since, name], 60)
        text = "".join(f"[{name}] {line}\n" for line in (result.stdout + result.stderr).splitlines())
        (output / "logs" / f"{name}.log").write_text(text, encoding="utf-8")
        lines[name] = len(text.splitlines())
    meta = {"schema_version": 1, "source_type": "docker_container",
            "started_at": started.isoformat(), "duration_minutes": args.minutes,
            "rounds": rounds, "containers": list(CONTAINERS), "lines": lines}
    (output / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
