"""模块说明：按故障时间切分正常窗口与故障窗口。"""

from __future__ import annotations

import json
from pathlib import Path

from aiops_diag.data.adapters import parse_lines


# 方法说明：load_windows 解析单个案例并切分正常/故障窗口。
def load_windows(case_dir, source_type=None):
    case_dir = Path(case_dir)
    incident = json.loads((case_dir / "incident.json").read_text(encoding="utf-8"))
    logs = list((case_dir / "evidence/logs").glob("*.log"))
    if not logs:
        return None
    if source_type is None:
        source_type = "wsl" if "wsl_cases" in str(case_dir) else "docker_container"
    rows = parse_lines(source_type, logs[0].read_text(encoding="utf-8", errors="replace").splitlines(),
                       case_dir.name, incident["timestamps"]["fault_start"])
    start = incident["timestamps"]["fault_start"]
    normal = [row for row in rows if (row.get("timestamp_utc") or "") < start]
    fault = [row for row in rows if (row.get("timestamp_utc") or "") >= start]
    return {"incident_id": incident["incident_id"], "source_type": source_type,
            "normal": normal, "fault": fault, "fault_start": start}
