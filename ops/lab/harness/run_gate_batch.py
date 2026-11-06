"""脚本说明：以 event_source=model 全量重放真实故障。"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "ops/lab/harness")
sys.path.insert(0, "src")
from ingest import FrozenCodeRetriever, ingest
from aiops_diag.detection.source_templates import SourceTemplateMatcher
from aiops_diag.knowledge.config import load as load_knowledge
from aiops_diag.knowledge.release import FrozenRetriever


# 方法说明：main 逐案例走检测门禁并触发诊断。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--work", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--source-type", choices=("docker_container", "wsl"), required=True)
    parser.add_argument("--detector", required=True)
    parser.add_argument("--template-dir", required=True)
    parser.add_argument("--gate-output", required=True)
    args = parser.parse_args(argv)
    work = Path(args.work)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    Path(args.database).unlink(missing_ok=True)
    shutil.copyfile(args.source_db, args.database)
    database = sqlite3.connect(args.database)
    for table in ("incident_reports", "agent_runs", "agent_evidence", "agent_tool_calls"):
        database.execute(f"DELETE FROM {table}")
    database.commit()
    database.close()
    retriever = FrozenCodeRetriever(
        FrozenRetriever(load_knowledge("resources/configs/retrieval.yaml")))
    matcher = SourceTemplateMatcher(args.template_dir)
    cases = [path for path in sorted(Path(args.cases).glob("*"))
             if (path / "incident.json").is_file()]
    gates = []
    started = time.time()
    for index, case in enumerate(cases, 1):
        target = work / case.name
        shutil.copytree(case, target)
        mapping = ingest(str(target), args.database, agent_backend="native",
                         retriever_kind="frozen", retriever=retriever,
                         template_dir=args.template_dir, matcher=matcher,
                         source_type=args.source_type, event_source="model",
                         detector_path=args.detector)
        gates.append(mapping)
        if index % 20 == 0:
            print(f"{index}/{len(cases)} elapsed={time.time()-started:.0f}s", flush=True)
    Path(args.gate_output).write_text(json.dumps(gates, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    passed = sum(1 for row in gates if row.get("event_id"))
    print("done", len(gates), "passed", passed, "rejected", len(gates) - passed, flush=True)
    subprocess.run([sys.executable, "ops/scripts/evaluate_incidents.py",
                    "--database", args.database, "--cases", str(work),
                    "--output", args.output], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
