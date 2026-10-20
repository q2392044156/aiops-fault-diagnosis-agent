import json
from pathlib import Path

import pytest

from aiops_diag.retrieval.candidate_pool_v11 import build_packet, validate
from aiops_diag.retrieval.freeze_reviewed_v11 import freeze
from aiops_diag.retrieval.protocol_v11 import validate_protocol
from aiops_diag.retrieval.review_v11 import validate_submission


ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "evaluation/v1.1/public_candidate_pool_60.jsonl"
PACKET = ROOT / "evaluation/v1.1/public_review_packet_60.jsonl"
CARDS = ROOT / "knowledge/cards"
COMPARISON = [ROOT / name for name in (
    "evaluation/v1.1/development.jsonl",
    "evaluation/v1.1/calibration.jsonl",
    "evaluation/v1.1/independent_test.jsonl",
    "knowledge/evaluation/rdev.jsonl",
    "knowledge/evaluation/rtest.jsonl",
)]


def _reviewed_rows():
    proposed = [json.loads(line) for line in POOL.read_text(
        encoding="utf-8").splitlines()]
    reviewed = [json.loads(line) for line in PACKET.read_text(
        encoding="utf-8").splitlines()]
    for source, row in zip(proposed, reviewed):
        row["review_has_answer"] = source["proposed_has_answer"]
        row["review_evidence_unit_ids"] = ([source["proposed_evidence_unit_id"]]
                                           if source["proposed_evidence_unit_id"] else [])
        row["reviewer_id"] = "external_hdfs_reviewer"
        row["review_notes"] = "Independent structural test fixture."
    return reviewed


def _write_rows(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                            for row in rows), encoding="utf-8")


def test_public_candidate_pool_is_blinded_complete_and_nonduplicate():
    result = validate(POOL, PACKET, CARDS, COMPARISON)
    assert result["queries"] == 60
    assert result["proposed_answerable"] == 40
    assert result["proposed_no_answer"] == 20
    assert result["versions"] == ["3.4.1", "3.4.2"]
    packet = [json.loads(line) for line in PACKET.read_text(
        encoding="utf-8").splitlines()]
    assert all("proposed_has_answer" not in row for row in packet)
    assert all("family_id" not in row for row in packet)
    assert all(row["review_has_answer"] is None for row in packet)


def test_public_candidate_packet_builder_refuses_overwrite(tmp_path):
    output = tmp_path / "packet.jsonl"
    assert build_packet(POOL, output)["queries"] == 60
    assert output.read_bytes() == PACKET.read_bytes()
    with pytest.raises(FileExistsError):
        build_packet(POOL, output)


def test_public_candidate_pool_rejects_label_leak(tmp_path):
    rows = [json.loads(line) for line in PACKET.read_text(
        encoding="utf-8").splitlines()]
    rows[0]["proposed_has_answer"] = True
    changed = tmp_path / "leaked.jsonl"
    changed.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                               for row in rows), encoding="utf-8")
    with pytest.raises(ValueError, match="leaked"):
        validate(POOL, changed, CARDS, COMPARISON)


def test_public_candidate_pool_accepts_complete_external_review_structure(tmp_path):
    submission = tmp_path / "submission.jsonl"
    _write_rows(submission, _reviewed_rows())
    result = validate_submission(POOL, PACKET, submission, CARDS)
    assert result["status"] == "STRUCTURALLY_REVIEWED_NOT_ADJUDICATED"
    assert result["disagreement_count"] == 0


def test_reviewed_candidate_pool_freezes_to_release_ready_protocol(tmp_path):
    submission = tmp_path / "submission.jsonl"
    _write_rows(submission, _reviewed_rows())
    output = tmp_path / "reviewed_protocol"
    result = freeze(ROOT / "evaluation/v1.1/protocol.json", POOL, PACKET,
                    submission, CARDS, output)
    assert result["status"] == "FROZEN_REVIEWED_PROTOCOL_REQUIRES_IDENTITY_AUDIT"
    assert result["readiness"]["release_ready"] is True
    checked = validate_protocol(output / "protocol.json", require_release_ready=True)
    assert checked["splits"]["independent_test"] == {
        "queries": 60, "answerable": 40, "no_answer": 20,
        "versions": ["3.4.1", "3.4.2"],
        "source_dates": ["2024-10-18", "2025-08-29"],
        "source_ids": ["apache_hdfs_341", "apache_hdfs_342",
                       "apache_hdfs_design_341", "apache_hdfs_design_342"],
        "annotation_status": "independently_reviewed"}
    with pytest.raises(FileExistsError):
        freeze(ROOT / "evaluation/v1.1/protocol.json", POOL, PACKET,
               submission, CARDS, output)


def test_review_disagreement_cannot_be_frozen(tmp_path):
    reviewed = _reviewed_rows()
    reviewed[0]["review_has_answer"] = False
    reviewed[0]["review_evidence_unit_ids"] = []
    submission = tmp_path / "disagreement.jsonl"
    _write_rows(submission, reviewed)
    with pytest.raises(ValueError, match="adjudication"):
        freeze(ROOT / "evaluation/v1.1/protocol.json", POOL, PACKET,
               submission, CARDS, tmp_path / "rejected")
    adjudication = tmp_path / "adjudication.jsonl"
    _write_rows(adjudication, [{
        "candidate_id": "v11_public_001", "final_has_answer": True,
        "final_evidence_unit_ids": ["hdfs-datanode-heartbeat:evidence"],
        "adjudicator_id": "second_external_hdfs_reviewer",
        "adjudication_notes": "Official architecture and the frozen card support the evidence label."}])
    result = freeze(ROOT / "evaluation/v1.1/protocol.json", POOL, PACKET,
                    submission, CARDS, tmp_path / "adjudicated", adjudication)
    assert result["readiness"]["release_ready"] is True
    assert result["adjudicators"] == ["second_external_hdfs_reviewer"]
