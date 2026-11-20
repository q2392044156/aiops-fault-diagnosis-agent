"""验证按来源构建与加载 Drain3 模板。"""

import json

from offline.case.source_templates import SourceTemplateMatcher, build
from offline.ingestion.adapters import parse_lines


# _case 构造一个最小的实验案例目录。
def _case(root, name, lines):
    case = root / name
    (case / "evidence/logs").mkdir(parents=True)
    (case / "incident.json").write_text(json.dumps({"incident_id": name}), encoding="utf-8")
    (case / "evidence/logs" / f"{name}.log").write_text("\n".join(lines) + "\n",
                                                        encoding="utf-8")
    return case


# 验证模板构建、匹配与冻结词表。
def test_build_and_match_source_templates(tmp_path):
    cases = tmp_path / "cases"
    _case(cases, "case-a", [
        "[dn1] 2026-10-28 12:00:00 INFO  DataNode:1 - Receiving block blk_1",
        "[dn1] 2026-10-28 12:00:01 ERROR DataNode:2 - No space left on device",
    ])
    _case(cases, "case-b", [
        "[dn1] 2026-10-28 12:01:00 ERROR DataNode:2 - No space left on device",
    ])
    output = tmp_path / "templates"
    meta = build("docker_container", cases, output)
    assert meta["template_count"] >= 1
    matcher = SourceTemplateMatcher(output)
    row = parse_lines("docker_container",
                      ["[dn1] 2026-10-28 12:00:00 INFO  DataNode:1 - Receiving block blk_1"],
                      "case-a", "2026-10-28T00:00:00+00:00")[0]
    template_id = matcher.match(row)
    assert isinstance(template_id, int)
    assert matcher.is_known(template_id)
