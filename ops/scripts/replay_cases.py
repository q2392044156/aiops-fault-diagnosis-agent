"""真实案例重放：准备 132 例的 case 目录与 id 清单，并把重放结果与冻结基线逐条比对。

两条子命令：

- ``prepare``：从 ``runtime/unified4`` 的两份 source DB 读出 132 例的 incident_id，
  再到 ``ops/lab`` 的案例目录里把对应案例复制成两份独立的 case 集，
  这样重放不必改动原始案例目录。
- ``verify``：把 ``run_gate_batch.py`` 产出的 gates/eval JSON 与
  ``resources/evaluation/unified4`` 的冻结基线逐条比对，打印差异并给出判定。

用法见 ``documentation/REPRODUCTION_v2.md``。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

# 132 例来自这两份 source DB 的 incident_registry；数字是冻结基线的一部分。
SOURCES = {"docker": 81, "wsl": 51}
CASE_ROOTS = (
    "ops/lab/real_batch_cases",
    "ops/lab/wsl_cases",
    "ops/lab/network_cases",
    "ops/lab/recaptured_cases",
    "ops/lab/cases",
)


def _registry_ids(path: Path) -> list[str]:
    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT incident_id FROM incident_registry ORDER BY incident_id")
        return [row[0] for row in rows]


def _case_index(roots: list[Path]) -> tuple[dict[str, Path], list[str]]:
    index: dict[str, Path] = {}
    duplicates: list[str] = []
    for root in roots:
        for manifest in sorted(root.rglob("incident.json")):
            record = json.loads(manifest.read_text(encoding="utf-8"))
            incident_id = record["incident_id"]
            if incident_id in index:
                duplicates.append(f"{incident_id}: {index[incident_id]} / {manifest.parent}")
                continue
            index[incident_id] = manifest.parent
    return index, duplicates


def prepare(output: Path) -> int:
    index, duplicates = _case_index([ROOT / root for root in CASE_ROOTS])
    if duplicates:
        print("duplicate incident_id found in several case directories:", file=sys.stderr)
        for line in duplicates:
            print(f"  {line}", file=sys.stderr)
        return 1
    output.mkdir(parents=True, exist_ok=True)
    for name, expected in SOURCES.items():
        database = ROOT / f"runtime/unified4/{name}_source.sqlite3"
        if not database.is_file():
            print(f"缺少 source DB：{database}", file=sys.stderr)
            return 1
        ids = _registry_ids(database)
        if len(ids) != expected:
            print(f"{name}: incident_registry has {len(ids)} rows, frozen baseline expects {expected}", file=sys.stderr)
            return 1
        missing = [incident_id for incident_id in ids if incident_id not in index]
        if missing:
            print(f"{name}: {len(missing)} cases not found locally, e.g. {missing[:3]}", file=sys.stderr)
            return 1
        destination = output / f"cases_{name}{expected}"
        if destination.exists():
            shutil.rmtree(destination)
        for incident_id in ids:
            shutil.copytree(index[incident_id], destination / incident_id)
        (output / f"ids_{name}.json").write_text(json.dumps(ids, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{name}: {len(ids)} cases -> {destination.relative_to(ROOT)}")
    print("\nnext: replay both case sets with run_gate_batch.py, then run verify.")
    return 0


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _score_equal(left: Any, right: Any) -> bool:
    if isinstance(left, int | float) and isinstance(right, int | float):
        return abs(float(left) - float(right)) <= 1e-9
    return left == right


def _compare_events(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    old_events = old.get("events") or []
    new_events = new.get("events") or []
    if len(old_events) != len(new_events):
        problems.append(f"event count {len(old_events)} -> {len(new_events)}")
        return problems
    for position, (left, right) in enumerate(zip(old_events, new_events, strict=True), 1):
        if left.get("gate_reason") != right.get("gate_reason"):
            problems.append(f"event {position} gate_reason {left.get('gate_reason')} -> {right.get('gate_reason')}")
        if not _score_equal(left.get("gate_score"), right.get("gate_score")):
            problems.append(f"event {position} gate_score {left.get('gate_score')} -> {right.get('gate_score')}")
    return problems


def _compare_gates(name: str, old_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]]) -> list[str]:
    old = {row["incident_id"]: row for row in old_rows}
    new = {row["incident_id"]: row for row in new_rows}
    problems: list[str] = []
    for incident_id in sorted(set(old) - set(new)):
        problems.append(f"{incident_id}: missing in replay")
    for incident_id in sorted(set(new) - set(old)):
        problems.append(f"{incident_id}: not present in frozen baseline")
    for incident_id in sorted(set(old) & set(new)):
        if old[incident_id].get("gate_reason") != new[incident_id].get("gate_reason"):
            problems.append(
                f"{incident_id}: top-level gate_reason {old[incident_id].get('gate_reason')} -> {new[incident_id].get('gate_reason')}"
            )
        for detail in _compare_events(old[incident_id], new[incident_id]):
            problems.append(f"{incident_id}: {detail}")
    old_total = sum(len(row.get("events") or []) for row in old.values())
    new_total = sum(len(row.get("events") or []) for row in new.values())
    verdict = "PASS" if not problems else "FAIL"
    print(
        f"{name}: cases {len(old)} / {len(new)}, events {old_total} / {new_total}, diffs {len(problems)} -> {verdict}"
    )
    return problems


def _split_metrics(
    rows: list[dict[str, Any]],
    gates_rows: list[dict[str, Any]],
    split: dict[str, Any],
) -> dict[str, Any]:
    test = {row["incident_id"] for row in rows} & set(split["test"])
    train = {row["incident_id"] for row in rows} & set(split["train"])
    picked = {row["incident_id"]: bool(row["top1"]) for row in rows}
    events = {"test": 0, "train": 0}
    for row in gates_rows:
        bucket = "test" if row["incident_id"] in test else "train" if row["incident_id"] in train else None
        if bucket is None:
            continue
        events[bucket] += len(row.get("events") or [])
    return {
        "test_cases": len(test),
        "test_events": events["test"],
        "test_top1": sum(1 for incident_id in test if picked[incident_id]),
        "train_cases": len(train),
        "train_events": events["train"],
        "train_top1": sum(1 for incident_id in train if picked[incident_id]),
    }


def verify(replay: Path, reference: Path) -> int:
    problems: list[str] = []
    gates_rows: list[dict[str, Any]] = []
    for name in ("docker", "wsl"):
        gates = replay / f"{name}_gates2.json"
        if not gates.is_file():
            print(f"missing replay output: {gates}", file=sys.stderr)
            return 1
        replayed = _load(gates)
        gates_rows.extend(replayed)
        problems.extend(
            _compare_gates(
                name,
                _load(reference / f"{name}_gates.json"),
                replayed,
            )
        )

    rows: list[dict[str, Any]] = []
    for name in ("docker", "wsl"):
        path = replay / f"{name}_eval2.json"
        if not path.is_file():
            print(f"missing replay output: {path}", file=sys.stderr)
            return 1
        rows.extend(_load(path)["rows"])

    split = _load(reference / "split.json")
    stored = _load(reference / "results.json")
    actual = _split_metrics(rows, gates_rows, split)
    expected = {
        "test_cases": stored["test"]["cases"],
        "test_events": stored["test"]["events"],
        "test_top1": stored["test"]["case_top1"],
        "train_cases": stored["train"]["cases"],
        "train_events": stored["train"]["events"],
        "train_top1": stored["train"]["case_top1"],
    }
    print(f"split: {split['split']} / hash {split['split_hash'][:16]}")
    for key, value in actual.items():
        wanted = expected[key]
        same = abs(float(value) - float(wanted)) <= 1e-6
        print(f"  {key}: replay {value} / baseline {wanted:g} -> {'PASS' if same else 'FAIL'}")
        if not same:
            problems.append(f"{key}: replay {value} != baseline {wanted:g}")

    if problems:
        print(f"\n{len(problems)} differences:")
        for line in problems[:40]:
            print(f"  - {line}")
        return 1
    print("\nPASS: event segmentation, gate reasons/scores and case top-1 all match the frozen baseline.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare", help="准备 132 例的 case 目录与 id 清单")
    prepare_parser.add_argument("--output", type=Path, default=Path("runtime/repro"))
    verify_parser = sub.add_parser("verify", help="把重放结果与冻结基线逐条比对")
    verify_parser.add_argument("--replay", type=Path, default=Path("runtime/repro"))
    verify_parser.add_argument("--reference", type=Path, default=Path("resources/evaluation/unified4"))
    args = parser.parse_args()
    if args.command == "prepare":
        return prepare(args.output.resolve())
    return verify(args.replay.resolve(), args.reference.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
