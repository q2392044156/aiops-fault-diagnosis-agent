import json
from pathlib import Path

import pytest

from aiops_diag.retrieval.review_v11 import validate_packet, validate_submission


ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "evaluation/v1.1/review_pool.jsonl"
PACKET = ROOT / "evaluation/v1.1/review_packet.jsonl"
CARDS = ROOT / "knowledge/cards"


def _write(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")


def test_review_packet_hides_proposals_and_covers_pool(tmp_path):
    assert validate_packet(POOL, PACKET)["queries"] == 8
    rows = [json.loads(line) for line in PACKET.read_text(
        encoding="utf-8").splitlines()]
    rows[0]["proposed_has_answer"] = True
    altered = tmp_path / "altered.jsonl"
    _write(altered, rows)
    with pytest.raises(ValueError, match="leaked"):
        validate_packet(POOL, altered)


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
