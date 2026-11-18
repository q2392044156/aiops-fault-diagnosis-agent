"""跑完整数据准备、独立子集重建与审计（不下载）。"""
import json

from aiops_diag.common import config, save
from offline.ingestion.audit import audit
from offline.ingestion.pipeline import build, split, subset


def main():
    c = config("resources/configs/data.yaml")
    folder = build(c)
    print(f"Build complete: {folder}", flush=True)
    split(c)
    print("Split complete", flush=True)
    subset(c)
    first = json.loads((folder / "subset.json").read_text())
    subset(c)
    second = json.loads((folder / "subset.json").read_text())
    if first != second:
        raise RuntimeError("Subset reproduction differs")
    save(folder / "reproduction.json", {"passed": True, "membership_hash": first["membership_hash"],
                                       "line_membership_hash": first["line_membership_hash"], "artifacts": first["artifacts"]})
    print("Independent subset rebuild matches", flush=True)
    report = audit(c)
    print(json.dumps({k: report[k] for k in ("data_checks_pass", "counts", "label_counts", "split_label_counts",
         "automated_sample_count", "raw_duplicate_lines", "cross_split_normalized_sequence_hashes",
         "build_seconds", "peak_sampled_rss_bytes", "environment")}, indent=2))


if __name__ == "__main__":
    main()
