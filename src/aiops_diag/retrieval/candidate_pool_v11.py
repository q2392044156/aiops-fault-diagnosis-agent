"""Validate and blind the 60-question v1.1 public-document candidate pool."""

import json
import re
import unicodedata
from pathlib import Path

from aiops_diag.data.common import digest


VISIBLE = ("candidate_id", "query", "product_version", "source_url")
REVIEW = ("review_has_answer", "review_evidence_unit_ids", "reviewer_id", "review_notes")


def _rows(path):
    return [json.loads(line) for line in Path(path).read_text(
        encoding="utf-8").splitlines() if line.strip()]


def _normalized(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value).casefold())


def _knowledge_units(cards_dir):
    units = {}
    for path in Path(cards_dir).glob("*.json"):
        card = json.loads(path.read_text(encoding="utf-8"))
        for section in card["sections"]:
            units[f"{card['doc_id']}:{section['id']}"] = set(card["version_scope"])
    if not units:
        raise ValueError("Knowledge cards are unavailable")
    return units


def validate(pool_path, packet_path, cards_dir, comparison_files=()):
    pool, packet = _rows(pool_path), _rows(packet_path)
    if len(pool) != 60 or len(packet) != 60:
        raise ValueError("Candidate pool and packet must contain exactly 60 questions")
    if sum(row.get("proposed_has_answer") is True for row in pool) != 40:
        raise ValueError("Candidate pool must propose exactly 40 answerable questions")
    if sum(row.get("proposed_has_answer") is False for row in pool) != 20:
        raise ValueError("Candidate pool must propose exactly 20 no-answer questions")
    units = _knowledge_units(cards_dir)
    seen_ids, seen_families, seen_queries = set(), set(), set()
    comparison = set()
    for path in comparison_files:
        comparison.update(_normalized(row["query"]) for row in _rows(path))
    versions = set()
    for proposed, blank in zip(pool, packet):
        expected_pool = {*VISIBLE, "family_id", "proposed_has_answer",
                         "proposed_evidence_unit_id", "annotation_status"}
        if set(proposed) != expected_pool:
            raise ValueError("Candidate pool row has unexpected fields")
        if (set(blank) != set(VISIBLE) | set(REVIEW)
                or any(blank[name] != proposed[name] for name in VISIBLE)
                or blank["review_has_answer"] is not None
                or blank["review_evidence_unit_ids"] != []
                or blank["reviewer_id"] is not None
                or blank["review_notes"] is not None):
            raise ValueError("Blinded packet changed or leaked proposed labels")
        candidate_id, family = proposed["candidate_id"], proposed["family_id"]
        normalized = _normalized(proposed["query"])
        if (not candidate_id.startswith("v11_public_") or candidate_id in seen_ids
                or not family or family in seen_families or not normalized
                or normalized in seen_queries or normalized in comparison):
            raise ValueError("Candidate identity, family, or query is duplicate")
        seen_ids.add(candidate_id)
        seen_families.add(family)
        seen_queries.add(normalized)
        version = proposed["product_version"]
        versions.add(version)
        if (version not in {"3.4.1", "3.4.2"}
                or not proposed["source_url"].startswith(
                    f"https://hadoop.apache.org/docs/r{version}/")
                or proposed["annotation_status"] != "self_reviewed_candidate"):
            raise ValueError("Candidate source or annotation status is invalid")
        unit = proposed["proposed_evidence_unit_id"]
        if proposed["proposed_has_answer"] != bool(unit):
            raise ValueError("Proposed answer and evidence unit disagree")
        if unit:
            scope = units.get(unit, set())
            if version not in scope and "all-conceptual" not in scope:
                raise ValueError("Proposed evidence unit is missing or version-inapplicable")
    if versions != {"3.4.1", "3.4.2"}:
        raise ValueError("Candidate pool must cover HDFS 3.4.1 and 3.4.2")
    return {"schema_version": 1,
            "status": "SELF_REVIEWED_CANDIDATES_AWAITING_INDEPENDENT_REVIEW",
            "queries": len(pool), "proposed_answerable": 40,
            "proposed_no_answer": 20, "versions": sorted(versions),
            "pool_sha256": digest(pool_path), "packet_sha256": digest(packet_path),
            "limitation": "Structural validation does not verify label semantics or reviewer identity."}


def build_packet(pool_path, output_path):
    output_path = Path(output_path)
    if output_path.exists():
        raise FileExistsError("Candidate review packet already exists")
    rows = []
    for proposed in _rows(pool_path):
        rows.append({**{name: proposed[name] for name in VISIBLE},
                     "review_has_answer": None, "review_evidence_unit_ids": [],
                     "reviewer_id": None, "review_notes": None})
    output_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                                   for row in rows), encoding="utf-8")
    return {"queries": len(rows), "packet_sha256": digest(output_path)}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("pool", type=Path)
    build.add_argument("packet", type=Path)
    check = sub.add_parser("validate")
    check.add_argument("pool", type=Path)
    check.add_argument("packet", type=Path)
    check.add_argument("cards", type=Path)
    check.add_argument("comparison", nargs="*", type=Path)
    args = parser.parse_args()
    value = (build_packet(args.pool, args.packet) if args.command == "build" else
             validate(args.pool, args.packet, args.cards, args.comparison))
    print(json.dumps(value, ensure_ascii=False, indent=2))
