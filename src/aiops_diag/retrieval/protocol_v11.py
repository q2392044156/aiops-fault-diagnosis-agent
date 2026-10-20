"""Validate a sealed v1.1 retrieval evaluation protocol before blind testing."""

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

from aiops_diag.data.common import digest


SPLITS = ("development", "calibration", "independent_test")


def _inside(directory, relative):
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("Evaluation artifact escapes protocol directory")
    return path


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _normalized(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).casefold())


def validate_protocol(manifest_path, require_release_ready=False):
    """Return coverage and readiness; reject changed files and split leakage.

    A self-reviewed test set can be checked for structure, but cannot pass the
    release gate. This validator cannot replace a domain expert's label review.
    """
    manifest_path = Path(manifest_path)
    directory = manifest_path.resolve().parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 2 or set(manifest.get("splits", {})) != set(SPLITS):
        raise ValueError("v1.1 protocol requires three sealed splits")
    sources = {row["source_id"]: row for row in manifest.get("sources", [])}
    if len(sources) != len(manifest.get("sources", [])) or not sources:
        raise ValueError("Source catalog is missing or has duplicate IDs")
    for source in sources.values():
        date.fromisoformat(source["published_at"])
        if not source.get("url") or not source.get("product_version"):
            raise ValueError("Source provenance requires URL and product version")
    knowledge_units = None
    if manifest.get("knowledge_cards_dir"):
        cards_dir = (directory / manifest["knowledge_cards_dir"]).resolve()
        knowledge_units = {}
        for path in cards_dir.glob("*.json"):
            card = json.loads(path.read_text(encoding="utf-8"))
            for section in card["sections"]:
                knowledge_units[f"{card['doc_id']}:{section['id']}"] = set(
                    card["version_scope"])

    seen_ids, seen_families, seen_queries = set(), set(), set()
    legacy_queries = set()
    for relative in manifest.get("legacy_query_files", []):
        for row in _read_jsonl((directory / relative).resolve()):
            legacy_queries.add(_normalized(row["query"]))
            seen_families.add(row["family_id"])
    summary = {}
    split_dates = {}
    for split in SPLITS:
        entry = manifest["splits"][split]
        paths = {name: _inside(directory, entry[name]) for name in ("queries", "qrels")}
        for name, path in paths.items():
            if digest(path) != entry[f"{name}_sha256"]:
                raise ValueError(f"Sealed {split} {name} changed")
        queries, qrels = _read_jsonl(paths["queries"]), _read_jsonl(paths["qrels"])
        if not queries or not qrels:
            raise ValueError(f"{split} requires queries and qrels")
        answer_ids, query_versions = set(), {}
        versions, dates, source_ids = set(), set(), set()
        answerable = 0
        for row in queries:
            query_id, family_id = row["query_id"], row["family_id"]
            normalized = _normalized(row["query"])
            if (row.get("split") != split or not normalized or query_id in seen_ids
                    or family_id in seen_families or normalized in seen_queries
                    or normalized in legacy_queries):
                raise ValueError(f"{split} has duplicate, leaked or malformed query")
            seen_ids.add(query_id)
            seen_families.add(family_id)
            seen_queries.add(normalized)
            if not isinstance(row.get("has_answer"), bool):
                raise ValueError(f"{split} query requires a Boolean has_answer")
            if entry.get("annotation_status") == "independently_reviewed" and (
                    not row.get("annotator_id") or not row.get("reviewer_id")
                    or row["annotator_id"] == row["reviewer_id"]):
                raise ValueError(f"{split} lacks independent per-query review")
            if row["has_answer"]:
                answer_ids.add(query_id)
                answerable += 1
            query_versions[query_id] = row.get("product_version")
            source = sources.get(row.get("source_id"))
            if source is None or row.get("product_version") != source.get("product_version"):
                raise ValueError(f"{split} has an unknown or mismatched source version")
            dates.add(source["published_at"])
            versions.add(row["product_version"])
            source_ids.add(row["source_id"])
        if not 0 < answerable < len(queries):
            raise ValueError(f"{split} needs answerable and no-answer queries")
        related = set()
        for row in qrels:
            if (row["query_id"] not in answer_ids or not row.get("evidence_unit_id")
                    or row.get("relevance") not in (1, 2)):
                raise ValueError(f"{split} has invalid qrels")
            if knowledge_units is not None:
                scope = knowledge_units.get(row["evidence_unit_id"], set())
                if (query_versions[row["query_id"]] not in scope
                        and "all-conceptual" not in scope):
                    raise ValueError(f"{split} qrel has unknown or inapplicable evidence")
            related.add(row["query_id"])
        if related != answer_ids:
            raise ValueError(f"{split} answerable queries lack qrels")
        split_dates[split] = dates
        summary[split] = {"queries": len(queries), "answerable": answerable,
                          "no_answer": len(queries) - answerable,
                          "versions": sorted(versions), "source_dates": sorted(dates),
                          "source_ids": sorted(source_ids),
                          "annotation_status": entry.get("annotation_status")}

    test = summary["independent_test"]
    earlier = split_dates["development"] | split_dates["calibration"]
    ready = (knowledge_units is not None
             and len(manifest.get("legacy_query_files", [])) >= 2
             and test["annotation_status"] == "independently_reviewed"
             and test["queries"] >= 60 and test["no_answer"] >= 20
             and len(test["versions"]) >= 2 and len(test["source_dates"]) >= 2
             and max(earlier) < min(split_dates["independent_test"]))
    if require_release_ready and not ready:
        raise ValueError("Independent review and cross-time/version coverage are required")
    return {"schema_version": 2, "splits": summary, "release_ready": ready}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--release-ready", action="store_true")
    options = parser.parse_args()
    print(json.dumps(validate_protocol(options.manifest, options.release_ready),
                     ensure_ascii=False, indent=2))
