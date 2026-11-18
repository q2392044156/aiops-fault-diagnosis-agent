"""脚本说明：冻结新颖度检测器并生成可校验的 release。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path


# _sha 计算文件 SHA-256。
def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# main 生成 detector release。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--detector", required=True)
    parser.add_argument("--normal-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--release-id", default="novelty_v1")
    parser.add_argument("--source-type", default="docker_container")
    args = parser.parse_args(argv)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.detector, output / "detector.json")
    normal_files = sorted(Path(args.normal_dir).glob("*.log"))
    normal_hash = hashlib.sha256()
    for path in normal_files:
        normal_hash.update(path.name.encode("utf-8"))
        normal_hash.update(path.read_bytes())
    payload = json.loads(Path(args.detector).read_text(encoding="utf-8"))
    release = {
        "schema_version": 1, "release_id": args.release_id,
        "created_at": datetime.now(UTC).isoformat(),
        "source_type": args.source_type,
        "detector_sha256": _sha(output / "detector.json"),
        "normal_sha256": normal_hash.hexdigest(),
        "normal_files": [path.name for path in normal_files],
        "normal_windows": None,
        "threshold": payload.get("threshold"),
        "target_fpr": payload.get("target_fpr"),
        "model": payload.get("model", "template_novelty"),
    }
    (output / "detector_release.json").write_text(
        json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(release, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
