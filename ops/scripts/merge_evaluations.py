"""脚本说明：合并有效 Docker 子集与 WSL 原始/补采批次。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


# 方法说明：_load 读取 JSON。
def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# 方法说明：main 输出 v2 合并指标。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--docker", required=True)
    parser.add_argument("--wsl", required=True)
    parser.add_argument("--recaptured", required=True)
    parser.add_argument("--docker-citations", required=True)
    parser.add_argument("--wsl-citations", required=True)
    parser.add_argument("--recaptured-citations", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    docker = _load(args.docker)
    wsl = _load(args.wsl)
    rec = _load(args.recaptured)
    dc = _load(args.docker_citations)
    wc = _load(args.wsl_citations)
    rc = _load(args.recaptured_citations)
    events = docker["events"] + wsl["events"] + rec["events"]
    event_hits = docker["event_top1"] + wsl["event_top1"] + rec["event_top1"]
    cases = docker["incidents"] + wsl["incidents"] + rec["incidents"]
    case_hits = (docker["incident_any_top1"] + wsl["incident_any_top1"]
                 + rec["incident_any_top1"])
    gold = dc["gold_lines"] + wc["gold_lines"] + rc["gold_lines"]
    cited_gold = dc["cited_gold"] + wc["cited_gold"] + rc["cited_gold"]
    cited = dc["cited_lines"] + wc["cited_lines"] + rc["cited_lines"]
    payload = {
        "dataset": "merged_v2",
        "sources": {"docker_valid": docker["incidents"], "wsl_original": wsl["incidents"],
                    "wsl_recaptured": rec["incidents"]},
        "events": events, "event_top1": event_hits,
        "event_top1_rate": round(event_hits / events, 4) if events else None,
        "cases": cases, "case_top1": case_hits,
        "case_top1_rate": round(case_hits / cases, 4) if cases else None,
        "citations": {"gold": gold, "cited_gold": cited_gold, "cited": cited,
                      "coverage_micro": round(cited_gold / gold, 4) if gold else None,
                      "precision_micro": round(cited_gold / cited, 4) if cited else None},
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
