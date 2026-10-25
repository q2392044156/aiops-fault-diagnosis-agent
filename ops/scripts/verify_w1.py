# 模块说明：校验输入、产物和运行条件是否满足约定。
"""Run full preparation, independent subset rebuild and audit (no download)."""
import json

from aiops_diag.data.common import config, save
from aiops_diag.data.pipeline import build, split, subset
from aiops_diag.data.audit import audit


# 方法说明：`main` 完成当前步骤的业务处理；参数为 无显式业务参数。
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
