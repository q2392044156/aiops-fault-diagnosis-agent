"""Validate RC2 JSON, Markdown links, evidence hashes, and release hygiene."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = [
    ROOT / "README.md",
    ROOT / "deliverables/framework_rc2_acceptance_report.md",
]
JSON_FILES = [
    ROOT / "deliverables/results/framework_rc2_acceptance_manifest.json",
    ROOT / "deliverables/results/framework_offline_acceptance_rc2.json",
    ROOT / "deliverables/results/framework_online_acceptance_rc2.json",
    ROOT / "deliverables/results/framework_fault_recovery_acceptance_rc2.json",
    ROOT / "deliverables/results/framework_sealed_acceptance_rc2_once.json",
    ROOT / "deliverables/results/framework_rollback_drill_rc2_pending.json",
    ROOT / "evaluation/v1.1/framework_rc2_sealed_20261020/freeze_manifest.json",
    ROOT / "evaluation/v1.2/real_incident_protocol/manifest.json",
]
SCAN_ROOTS = [
    "README.md",
    "configs",
    "deployment",
    "deliverables",
    "evaluation",
    "scripts",
    "src",
    "tests",
]
TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".yaml", ".yml", ".py", ".ps1", ".toml", ".txt"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def markdown_missing_links(path: Path) -> list[str]:
    missing: list[str] = []
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
        target = target.strip().strip("<>")
        if target.startswith(("http://", "https://", "#")):
            continue
        relative = target.split("#", 1)[0]
        if relative and not (path.parent / relative).resolve().exists():
            missing.append(target)
    return missing


def iter_text_files() -> list[Path]:
    files: list[Path] = []
    for name in SCAN_ROOTS:
        root = ROOT / name
        if root.is_file():
            files.append(root)
            continue
        files.extend(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES
        )
    return files


def main() -> None:
    parsed = {path.relative_to(ROOT).as_posix(): json.loads(path.read_text(encoding="utf-8")) for path in JSON_FILES}
    acceptance = parsed["deliverables/results/framework_rc2_acceptance_manifest.json"]

    missing_links = {
        path.relative_to(ROOT).as_posix(): markdown_missing_links(path) for path in REPORTS
    }
    missing_links = {key: value for key, value in missing_links.items() if value}

    hash_mismatches: list[str] = []
    for item in acceptance["evidence_hashes"].values():
        target = ROOT / item["path"]
        if not target.exists() or digest(target) != item["sha256"]:
            hash_mismatches.append(item["path"])

    secret_patterns = {
        "deepseek_key_literal": re.compile(r"^[ \t]*DEEPSEEK_API_KEY[ \t]*[:=](?![ \t]*\$\{)(?![ \t]*你的Key)(?![ \t]*<)[ \t]*['\"]?([^\s'\"]+)", re.IGNORECASE | re.MULTILINE),
        "deepseek_tracking_literal": re.compile(r"^[ \t]*DEEPSEEK_TRACKING_ID[ \t]*[:=](?![ \t]*\$\{)(?![ \t]*你的Tracking_ID)(?![ \t]*<)[ \t]*['\"]?([^\s'\"]+)", re.IGNORECASE | re.MULTILINE),
        "generic_api_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    }
    secret_findings: list[dict[str, str]] = []
    for path in iter_text_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, pattern in secret_patterns.items():
            if pattern.search(text):
                secret_findings.append({"file": path.relative_to(ROOT).as_posix(), "pattern": name})

    log_files = [
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*.log")
        if not any(
            part in {"runtime", ".w10-env", ".uv-cache", ".git", "data", ".pytest-tmp", ".pytest_cache"}
            for part in path.parts
        )
    ]
    report = {
        "schema_version": 1,
        "status": "PASS" if not (missing_links or hash_mismatches or secret_findings or log_files) else "FAIL",
        "json_files_parsed": len(parsed),
        "markdown_files_checked": len(REPORTS),
        "missing_markdown_links": missing_links,
        "evidence_hash_mismatches": hash_mismatches,
        "secret_scan": {
            "env_file_scanned": False,
            "finding_count": len(secret_findings),
            "findings": secret_findings,
        },
        "raw_log_files_outside_excluded_runtime_or_data": log_files,
        "acceptance_status": acceptance["status"],
        "all_hard_gates_zero": acceptance["all_hard_gates_zero"],
    }
    output = ROOT / "deliverables/results/framework_rc2_document_validation.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
