"""v1.1 复核流程共用的 JSONL 读写：逐行解析、跳过空行，写出时保持中文不转义。"""

from __future__ import annotations

import json
from pathlib import Path


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text(
        encoding="utf-8").splitlines() if line.strip()]


def write_rows(path, rows):
    Path(path).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                                  for row in rows), encoding="utf-8")
