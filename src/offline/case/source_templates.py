"""用 Drain3 从正常日志中挖掘来源模板，并匹配新日志的出现情况。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from drain3.file_persistence import FilePersistence
from drain3.template_miner import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

from offline.ingestion.adapters import parse_lines
from offline.ingestion.redact import content


# _config 构造与主模板器一致的 Drain3 配置。
def _config():
    cfg = TemplateMinerConfig()
    cfg.drain_sim_th = 0.5
    cfg.drain_depth = 4
    cfg.drain_max_children = 100
    cfg.parametrize_numeric_tokens = False
    cfg.snapshot_interval_minutes = 10**9
    return cfg


# _case_logs 返回案例目录下的证据日志。
def _case_logs(cases):
    for case in sorted(Path(cases).glob("*")):
        if not (case / "incident.json").is_file():
            continue
        logs = list((case / "evidence/logs").glob("*.log"))
        if logs:
            yield case.name, logs[0]


# build 在指定来源的真实日志上拟合模板。
def build(source_type, cases, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    miner = TemplateMiner(FilePersistence(str(output / "state.bin")), _config())
    lines = 0
    for _case, log in _case_logs(cases):
        text = log.read_text(encoding="utf-8", errors="replace")
        rows = parse_lines(source_type, text.splitlines(), log.name,
                           "2026-10-28T00:00:00+00:00")
        for row in rows:
            miner.add_log_message(content(row))
            lines += 1
    miner.save_state("source-template-build")
    clusters = getattr(miner.drain, "clusters", [])
    meta = {
        "schema_version": 1,
        "source_type": source_type,
        "case_dir": str(Path(cases).resolve()),
        "line_count": lines,
        "template_count": len(clusters),
        "templates": [getattr(cluster, "get_template", lambda: "")()
                      for cluster in list(clusters)[:20]],
    }
    (output / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    return meta


# SourceTemplateMatcher 加载冻结模板并给日志行分配模板 ID。
class SourceTemplateMatcher:
    # __init__ 加载 state.bin。
    def __init__(self, directory):
        self.directory = Path(directory)
        meta = json.loads((self.directory / "meta.json").read_text(encoding="utf-8"))
        self.source_type = meta["source_type"]
        self.miner = TemplateMiner(FilePersistence(str(self.directory / "state.bin")),
                                   _config())
        self.miner.load_state()
        self.seen = {int(cluster.cluster_id) for cluster in
                     getattr(self.miner.drain, "clusters", [])}

    # match 返回模板 ID；新模板记为未知但仍返回 ID。
    def match(self, row):
        result = self.miner.add_log_message(content(row))
        cluster_id = int(result["cluster_id"])
        return cluster_id

    # is_known 判断该 ID 是否在冻结词表中。
    def is_known(self, cluster_id):
        return int(cluster_id) in self.seen


# main 提供 build 子命令。
def main(argv=None):
    parser = argparse.ArgumentParser(description="Build per-source Drain3 templates")
    sub = parser.add_subparsers(dest="command", required=True)
    builder = sub.add_parser("build")
    builder.add_argument("--source", required=True,
                         choices=("docker_container", "wsl"))
    builder.add_argument("--cases", required=True)
    builder.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    result = build(args.source, args.cases, args.output)
    print(json.dumps({k: result[k] for k in ("source_type", "line_count",
                                             "template_count")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
