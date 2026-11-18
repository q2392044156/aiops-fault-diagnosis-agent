"""批量运行受控实验，汇总根因指标与 MTTD。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

# ROOT 指向仓库根目录。
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_case import run_case


# _evaluator 动态加载指标脚本，避免把 ops/scripts 变成包。
def _evaluator():
    spec = importlib.util.spec_from_file_location(
        "evaluate_incidents", ROOT / "ops" / "scripts" / "evaluate_incidents.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# main 按故障族批量跑实验并写出汇总结果。
def main(argv=None):
    parser = argparse.ArgumentParser(description="Run a batch of lab cases")
    parser.add_argument("--per-fault", type=int, default=7)
    parser.add_argument("--counts", default=None)
    parser.add_argument("--faults", default="DN_VOLUME,DN_HEARTBEAT,NN_SAFE_MODE")
    parser.add_argument("--database", default=str(ROOT / "runtime/lab/batch.sqlite3"))
    parser.add_argument("--cases", default=str(ROOT / "ops/lab/cases"))
    parser.add_argument("--output", default=str(ROOT / "resources/evaluation/lab/batch"))
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--observe", type=int, default=15)
    parser.add_argument("--require-signal", action="store_true")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    faults = [name.strip() for name in args.faults.split(",") if name.strip()]
    if args.counts:
        counts = {name: int(value) for name, value in
                  (item.split("=") for item in args.counts.split(","))}
    else:
        counts = {fault: (args.per_fault if fault != "NN_SAFE_MODE"
                          else max(1, args.per_fault - 1)) for fault in faults}
    runs = []
    for fault in faults:
        for _ in range(counts.get(fault, 0)):
            runs.append(run_case(fault, args.observe, dry_run=not args.real,
                                 import_db=args.database, case_root=args.cases,
                                 ingest_db=args.database,
                                 require_signal=args.require_signal))
    evaluator = _evaluator()
    from aiops_diag.platform.db import Database
    result = evaluator.evaluate(Database(args.database), args.cases)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(json.dumps(
        {"runs": runs, **result}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    table = evaluator.markdown(result)
    output.with_suffix(".md").write_text(table + "\n", encoding="utf-8")
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
