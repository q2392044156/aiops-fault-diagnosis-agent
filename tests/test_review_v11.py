"""模块说明：验证 review v11 相关功能、边界和回归行为。"""

import json
from pathlib import Path

import pytest

from aiops_diag.knowledge.review_v11 import validate_packet, validate_submission


# 变量说明：`ROOT` 保存本模块或数据模型使用的稳定值。
ROOT = Path(__file__).resolve().parents[1]
# 变量说明：`POOL` 保存本模块或数据模型使用的稳定值。
POOL = ROOT / "resources/evaluation/v1.1/review_pool.jsonl"
# 变量说明：`PACKET` 保存本模块或数据模型使用的稳定值。
PACKET = ROOT / "resources/evaluation/v1.1/review_packet.jsonl"
# 变量说明：`CARDS` 保存本模块或数据模型使用的稳定值。
CARDS = ROOT / "resources/knowledge/cards"


# 方法说明：`_write` 完成当前步骤的业务处理；参数为 `path`、`rows`。
def _write(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")


# 方法说明：`test_review_packet_hides_proposals_and_covers_pool` 完成当前步骤的业务处理；参数为 `tmp_path`。
def test_review_packet_hides_proposals_and_covers_pool(tmp_path):
    assert validate_packet(POOL, PACKET)["queries"] == 8
    rows = [json.loads(line) for line in PACKET.read_text(
        encoding="utf-8").splitlines()]
    rows[0]["proposed_has_answer"] = True
    altered = tmp_path / "altered.jsonl"
    _write(altered, rows)
    with pytest.raises(ValueError, match="leaked"):
        validate_packet(POOL, altered)


# 方法说明：`test_review_submission_checks_evidence_scope_and_keeps_disagreements` 完成当前步骤的业务处理；参数为 `tmp_path`。
def test_review_submission_checks_evidence_scope_and_keeps_disagreements(tmp_path):
    pool = [json.loads(line) for line in POOL.read_text(
        encoding="utf-8").splitlines()]
    reviewed = [json.loads(line) for line in PACKET.read_text(
        encoding="utf-8").splitlines()]
    for proposal, row in zip(pool, reviewed):
        row["review_has_answer"] = proposal["proposed_has_answer"]
        row["review_evidence_unit_ids"] = ([proposal["proposed_evidence_unit_id"]]
                                            if proposal["proposed_evidence_unit_id"] else [])
        row["reviewer_id"] = "independent_reviewer_example"
        row["review_notes"] = "Checked against the frozen knowledge card."
    path = tmp_path / "reviewed.jsonl"
    _write(path, reviewed)
    result = validate_submission(POOL, PACKET, path, CARDS)
    assert result["status"] == "STRUCTURALLY_REVIEWED_NOT_ADJUDICATED"
    assert result["disagreement_count"] == 0
    reviewed[0]["review_has_answer"] = False
    reviewed[0]["review_evidence_unit_ids"] = []
    _write(path, reviewed)
    assert validate_submission(POOL, PACKET, path, CARDS)["disagreement_ids"] == [
        "v11_pool_001"]
    reviewed[0]["review_has_answer"] = True
    reviewed[0]["review_evidence_unit_ids"] = ["hdfs-safemode:evidence"]
    _write(path, reviewed)
    with pytest.raises(ValueError, match="version-inapplicable"):
        validate_submission(POOL, PACKET, path, CARDS)
