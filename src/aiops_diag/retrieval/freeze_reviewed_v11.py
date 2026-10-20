"""Freeze an externally reviewed v1.1 candidate pool into a new protocol directory."""

import json
import os
import shutil
import uuid
from pathlib import Path

from aiops_diag.data.common import digest, save

from .candidate_pool_v11 import _knowledge_units, _rows, validate as validate_pool
from .protocol_v11 import validate_protocol
from .review_v11 import validate_submission


def _relative(source, destination_directory):
    source, destination_directory = Path(source).resolve(), destination_directory.resolve()
    try:
        return os.path.relpath(source, destination_directory).replace("\\", "/")
    except ValueError:
        # Windows cannot express a relative path across drive letters. External
        # frozen cards and legacy sets may therefore remain absolute references.
        return source.as_posix()


def freeze(template_protocol, pool_path, packet_path, submission_path,
           cards_dir, output_dir, adjudication_path=None):
    """Create a sealed protocol only when the external review agrees with every label."""
    template_protocol = Path(template_protocol).resolve()
    template_dir = template_protocol.parent
    template = json.loads(template_protocol.read_text(encoding="utf-8"))
    comparisons = [template_dir / template["splits"][name]["queries"]
                   for name in ("development", "calibration", "independent_test")]
    comparisons.extend(template_dir / path for path in template.get("legacy_query_files", []))
    pool_status = validate_pool(pool_path, packet_path, cards_dir, comparisons)
    review = validate_submission(pool_path, packet_path, submission_path, cards_dir)
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("Reviewed protocol directory already exists")
    proposed, reviewed = _rows(pool_path), _rows(submission_path)
    final_labels = {row["candidate_id"]: {
        "has_answer": row["review_has_answer"],
        "evidence_unit_ids": row["review_evidence_unit_ids"],
        "reviewer_id": row["reviewer_id"]} for row in reviewed}
    adjudicators = set()
    disagreement_ids = set(review["disagreement_ids"])
    if disagreement_ids:
        if adjudication_path is None:
            raise ValueError("Review disagreements require human adjudication before freezing")
        units = _knowledge_units(cards_dir)
        adjudication = _rows(adjudication_path)
        if {row.get("candidate_id") for row in adjudication} != disagreement_ids:
            raise ValueError("Adjudication must cover exactly the review disagreements")
        versions = {row["candidate_id"]: row["product_version"] for row in proposed}
        for row in adjudication:
            expected = {"candidate_id", "final_has_answer", "final_evidence_unit_ids",
                        "adjudicator_id", "adjudication_notes"}
            reviewer = final_labels[row["candidate_id"]]["reviewer_id"]
            if (set(row) != expected or not isinstance(row["final_has_answer"], bool)
                    or not isinstance(row["final_evidence_unit_ids"], list)
                    or row["final_has_answer"] != bool(row["final_evidence_unit_ids"])
                    or len(row["final_evidence_unit_ids"]) != len(set(row["final_evidence_unit_ids"]))
                    or not isinstance(row["adjudicator_id"], str)
                    or not row["adjudicator_id"].strip()
                    or row["adjudicator_id"].strip().casefold() in {"project", "codex"}
                    or row["adjudicator_id"].strip() == reviewer
                    or not isinstance(row["adjudication_notes"], str)
                    or not row["adjudication_notes"].strip()):
                raise ValueError("Adjudication is incomplete or not independent")
            for unit in row["final_evidence_unit_ids"]:
                scope = units.get(unit, set())
                if versions[row["candidate_id"]] not in scope and "all-conceptual" not in scope:
                    raise ValueError("Adjudication cites missing or version-inapplicable evidence")
            adjudicator = row["adjudicator_id"].strip()
            adjudicators.add(adjudicator)
            final_labels[row["candidate_id"]] = {
                "has_answer": row["final_has_answer"],
                "evidence_unit_ids": row["final_evidence_unit_ids"],
                "reviewer_id": adjudicator}
    elif adjudication_path is not None:
        raise ValueError("Adjudication was supplied but the review has no disagreements")
    sources = {(row["product_version"], row["url"]): row["source_id"]
               for row in template["sources"]}
    queries, qrels = [], []
    for source in proposed:
        source_id = sources.get((source["product_version"], source["source_url"]))
        if source_id is None:
            raise ValueError("Reviewed question source is absent from the protocol catalog")
        query_id = source["candidate_id"]
        final = final_labels[query_id]
        queries.append({"query_id": query_id, "family_id": source["family_id"],
                        "split": "independent_test", "query": source["query"],
                        "has_answer": final["has_answer"],
                        "source_id": source_id,
                        "product_version": source["product_version"],
                        "annotator_id": "project_candidate_author",
                        "reviewer_id": final["reviewer_id"]})
        qrels.extend({"query_id": query_id, "evidence_unit_id": unit, "relevance": 1}
                     for unit in final["evidence_unit_ids"])
    staging = output_dir.parent / f".{output_dir.name}.{uuid.uuid4().hex}.partial"
    try:
        staging.mkdir(parents=True)
        split_entries = {}
        for name in ("development", "calibration"):
            entry = template["splits"][name]
            targets = {}
            for field in ("queries", "qrels"):
                source = (template_dir / entry[field]).resolve()
                target = staging / f"{name}{'_qrels' if field == 'qrels' else ''}.jsonl"
                shutil.copyfile(source, target)
                targets[field] = target
            split_entries[name] = {
                "queries": targets["queries"].name,
                "queries_sha256": digest(targets["queries"]),
                "qrels": targets["qrels"].name,
                "qrels_sha256": digest(targets["qrels"]),
                "annotation_status": entry["annotation_status"],
            }
        query_path, qrel_path = staging / "independent_test.jsonl", staging / "independent_test_qrels.jsonl"
        query_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                                      for row in queries), encoding="utf-8")
        qrel_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                                    for row in qrels), encoding="utf-8")
        split_entries["independent_test"] = {
            "queries": query_path.name, "queries_sha256": digest(query_path),
            "qrels": qrel_path.name, "qrels_sha256": digest(qrel_path),
            "annotation_status": "independently_reviewed",
        }
        protocol = {"schema_version": 2, "status": "candidate_independently_reviewed",
                    "knowledge_cards_dir": _relative(cards_dir, staging),
                    "sources": template["sources"],
                    "legacy_query_files": [_relative(template_dir / path, staging)
                                           for path in template.get("legacy_query_files", [])],
                    "splits": split_entries,
                    "review_provenance": {
                        "pool_sha256": pool_status["pool_sha256"],
                        "packet_sha256": pool_status["packet_sha256"],
                        "submission_sha256": digest(submission_path),
                        "reviewers": review["reviewers"],
                        "adjudication_sha256": (digest(adjudication_path)
                                                if adjudication_path else None),
                        "adjudicators": sorted(adjudicators),
                        "identity_verification": "external_process_required",
                    }}
        save(staging / "protocol.json", protocol)
        readiness = validate_protocol(staging / "protocol.json", require_release_ready=True)
        save(staging / "freeze_manifest.json", {
            "schema_version": 1,
            "status": "FROZEN_REVIEWED_PROTOCOL_REQUIRES_IDENTITY_AUDIT",
            "protocol_sha256": digest(staging / "protocol.json"),
            "submission_sha256": digest(submission_path),
            "reviewers": review["reviewers"], "adjudicators": sorted(adjudicators),
            "adjudication_sha256": (digest(adjudication_path) if adjudication_path else None),
            "readiness": readiness,
            "limitation": "The tool validates reviewer identifiers and labels structurally; a human owner must verify reviewer identity and independence."})
        os.replace(staging, output_dir)
        return json.loads((output_dir / "freeze_manifest.json").read_text(encoding="utf-8"))
    finally:
        if staging.exists() and staging.resolve().parent == output_dir.parent.resolve():
            shutil.rmtree(staging)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("template_protocol", "pool", "packet", "submission", "cards", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--adjudication", type=Path)
    args = parser.parse_args()
    result = freeze(args.template_protocol, args.pool, args.packet, args.submission,
                    args.cards, args.output, args.adjudication)
    print(json.dumps(result, ensure_ascii=False, indent=2))
