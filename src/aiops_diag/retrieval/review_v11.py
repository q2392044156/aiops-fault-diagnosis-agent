"""Validate blinded public-document review submissions without promoting labels."""

import json
from pathlib import Path

from aiops_diag.data.common import digest, save


VISIBLE = ("candidate_id", "query", "product_version", "source_url")
REVIEW = ("review_has_answer", "review_evidence_unit_ids", "reviewer_id", "review_notes")


def _rows(path):
    return [json.loads(line) for line in Path(path).read_text(
        encoding="utf-8").splitlines() if line.strip()]


def _units(cards_dir):
    units = {}
    for path in Path(cards_dir).glob("*.json"):
        card = json.loads(path.read_text(encoding="utf-8"))
        for section in card["sections"]:
            units[f"{card['doc_id']}:{section['id']}"] = set(card["version_scope"])
    if not units:
        raise ValueError("Knowledge cards are unavailable")
    return units


def validate_packet(pool_path, packet_path):
    """Ensure the packet contains every question but no proposed answer fields."""
    pool, packet = _rows(pool_path), _rows(packet_path)
    if not pool or len(pool) != len(packet):
        raise ValueError("Review packet does not cover the candidate pool")
    ids = set()
    for original, blinded in zip(pool, packet):
        if (set(blinded) != set(VISIBLE) | set(REVIEW)
                or any(blinded[name] != original[name] for name in VISIBLE)
                or any(blinded[name] is not None for name in
                       ("review_has_answer", "reviewer_id", "review_notes"))
                or blinded["review_evidence_unit_ids"] != []
                or blinded["candidate_id"] in ids):
            raise ValueError("Review packet changed or leaked proposed labels")
        ids.add(blinded["candidate_id"])
    return {"schema_version": 1, "queries": len(packet),
            "review_tool_sha256": digest(__file__),
            "pool_sha256": digest(pool_path), "packet_sha256": digest(packet_path)}


def validate_submission(pool_path, packet_path, submission_path, cards_dir):
    """Check review completeness and disagreements; do not mark a test release ready."""
    packet_manifest = validate_packet(pool_path, packet_path)
    pool, packet, reviewed = _rows(pool_path), _rows(packet_path), _rows(submission_path)
    if len(reviewed) != len(packet):
        raise ValueError("Review submission has missing or extra questions")
    units = _units(cards_dir)
    disagreements = []
    reviewers = set()
    for proposed, blank, row in zip(pool, packet, reviewed):
        if (set(row) != set(VISIBLE) | set(REVIEW)
                or any(row[name] != blank[name] for name in VISIBLE)
                or not isinstance(row["review_has_answer"], bool)
                or not isinstance(row["review_evidence_unit_ids"], list)
                or not isinstance(row["reviewer_id"], str)
                or not row["reviewer_id"].strip()
                or row["reviewer_id"].casefold() in {"project", "codex"}
                or not isinstance(row["review_notes"], str)
                or not row["review_notes"].strip()):
            raise ValueError("Review submission is incomplete or malformed")
        evidence = row["review_evidence_unit_ids"]
        if row["review_has_answer"] != bool(evidence) or len(evidence) != len(set(evidence)):
            raise ValueError("Review answer and evidence IDs disagree")
        for unit in evidence:
            if (not isinstance(unit, str) or unit not in units
                    or row["product_version"] not in units[unit]
                    and "all-conceptual" not in units[unit]):
                raise ValueError("Review cites missing or version-inapplicable evidence")
        reviewers.add(row["reviewer_id"].strip())
        proposed_units = ([proposed["proposed_evidence_unit_id"]]
                          if proposed["proposed_evidence_unit_id"] else [])
        if (row["review_has_answer"] != proposed["proposed_has_answer"]
                or set(evidence) != set(proposed_units)):
            disagreements.append(row["candidate_id"])
    return {**packet_manifest, "status": "STRUCTURALLY_REVIEWED_NOT_ADJUDICATED",
            "submission_sha256": digest(submission_path),
            "reviewers": sorted(reviewers), "disagreement_count": len(disagreements),
            "disagreement_ids": disagreements,
            "requires_adjudication": bool(disagreements)}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pool", type=Path)
    parser.add_argument("packet", type=Path)
    parser.add_argument("submission", type=Path)
    parser.add_argument("knowledge_cards", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = validate_submission(args.pool, args.packet, args.submission,
                                 args.knowledge_cards)
    if args.output.exists():
        raise FileExistsError("Review result already exists")
    save(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
