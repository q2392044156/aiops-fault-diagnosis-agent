"""模块说明：对同一批报告做上下文策略消融（全量 / 压缩 / 最小）。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# 变量说明：ROOT 指向仓库根目录，便于脚本在任意工作目录运行。
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from pydantic import ValidationError

from aiops_diag.diagnosis.context_builder import build_context
from aiops_diag.diagnosis.engine import REPORT_PROMPT
from aiops_diag.diagnosis.schemas import GeneratedReportBody
from aiops_diag.knowledge.generation.client import (BudgetLedger, DeepSeekClient,
                                                    DeepSeekError)
from aiops_diag.platform.db import Database

# 变量说明：BUDGET 限制实验花费。
BUDGET = {"max_total_tokens": 500000, "max_cost_cny": 5.0, "max_input_tokens_per_call": 10000,
          "input_cny_per_million": 2.0, "output_cny_per_million": 8.0}


# 方法说明：_load_env 读取 .env，已存在的环境变量优先。
def _load_env(path):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, _, value = line.partition("=")
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


# 方法说明：_client 构造带预算账本的 DeepSeek 客户端。
def _client(args):
    cfg = {"provider": {"name": "deepseek", "base_url": "https://api.deepseek.com",
                        "model": args.model, "api_key_env": "DEEPSEEK_API_KEY",
                        "api_key_file_env": "DEEPSEEK_API_KEY_FILE",
                        "tracking_id_env": "DEEPSEEK_TRACKING_ID",
                        "tracking_id_file_env": "DEEPSEEK_TRACKING_ID_FILE",
                        "timeout_seconds": 30, "overall_timeout_seconds": 45,
                        "max_tokens": 3000, "temperature": 0},
           "budget": BUDGET, "paths": {}}
    ledger = BudgetLedger(ROOT / "runtime" / "context_budget.json", BUDGET)
    return DeepSeekClient(cfg, ledger=ledger)


# 方法说明：_cases 从数据库读取可复用的报告，重建事件与证据。
def _cases(database, limit):
    rows = database.all(
        "SELECT report_json FROM incident_reports ORDER BY created_at")
    cases = []
    for row in rows:
        body = json.loads(row["report_json"])
        if len(body.get("evidence") or []) < 2:
            continue
        window = body.get("observation_window") or {}
        anomaly = body.get("anomaly") or {}
        cases.append({
            "event": {"event_id": body.get("incident_id"), "start_time": window.get("start"),
                      "end_time": window.get("end"), "max_anomaly_score": anomaly.get("score"),
                      "threshold": anomaly.get("threshold")},
            "hypotheses": body.get("hypotheses") or [],
            "evidence": body.get("evidence") or [],
        })
        if limit and len(cases) >= limit:
            break
    return cases


# 方法说明：_citation_check 校验报告引用是否合法，并统计是否同时引用日志与知识。
def _citation_check(body, package):
    kinds = {row["evidence_id"]: row["kind"] for row in package["evidence"]}
    cited = set()
    for item in body.hypotheses:
        cited.update(item.support_ids)
        cited.update(item.counter_ids)
    for item in body.checks:
        cited.update(item.citation_ids)
    allowed = set(package["allowed_evidence_ids"])
    used = {kinds[name] for name in cited if name in kinds}
    return cited <= allowed, {"log"} <= used and {"doc"} <= used


# 方法说明：main 依次运行三种策略并汇总质量、token 与延迟。
def main(argv=None):
    parser = argparse.ArgumentParser(description="Context strategy ablation")
    parser.add_argument("--database", required=True)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--budget", type=int, default=500)
    parser.add_argument("--strategies", default="full,compressed,minimal")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--output", default=str(ROOT / "resources/evaluation/context/result"))
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    _load_env(Path(args.env_file))
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY is not configured")
        return 2

    cases = _cases(Database(args.database), args.limit)
    client = _client(args)
    strategies = [name.strip() for name in args.strategies.split(",") if name.strip()]
    details, summary = {}, {}
    try:
        for strategy in strategies:
            rows = []
            for case in cases:
                built = build_context(case["event"], case["hypotheses"], case["evidence"],
                                      budget_tokens=args.budget, strategy=strategy)
                messages = [{"role": "system", "content": REPORT_PROMPT},
                            {"role": "user", "content": json.dumps(
                                built["package"], ensure_ascii=False)}]
                started = time.perf_counter()
                schema_ok = citations_ok = both_kinds = False
                usage, error = {}, None
                try:
                    value, usage = client.complete_json(messages)
                    body = GeneratedReportBody.model_validate(value)
                    schema_ok = True
                    citations_ok, both_kinds = _citation_check(body, built["package"])
                except (ValidationError, ValueError, DeepSeekError) as exc:
                    schema_ok = False
                    error = f"{type(exc).__name__}: {str(exc)[:160]}"
                rows.append({"strategy": strategy,
                             "context_tokens": built["meta"]["estimated_tokens"],
                             "evidence_sent": built["meta"]["evidence_sent"],
                             "budget_exceeded": built["meta"]["budget_exceeded"],
                             "schema_ok": schema_ok, "citations_ok": citations_ok,
                             "both_kinds": both_kinds, "error": error,
                             "input_tokens": usage.get("input_tokens", 0),
                             "output_tokens": usage.get("output_tokens", 0),
                             "elapsed_ms": round((time.perf_counter() - started) * 1000, 1)})
            total = len(rows)
            details[strategy] = rows
            summary[strategy] = {
                "runs": total,
                "schema_pass_rate": round(sum(r["schema_ok"] for r in rows) / total, 4),
                "citation_valid_rate": round(sum(r["citations_ok"] for r in rows) / total, 4),
                "both_kinds_rate": round(sum(r["both_kinds"] for r in rows) / total, 4),
                "avg_context_tokens": round(sum(r["context_tokens"] for r in rows) / total, 1),
                "avg_prompt_tokens": round(sum(r["input_tokens"] for r in rows) / total, 1),
                "avg_evidence_sent": round(sum(r["evidence_sent"] for r in rows) / total, 2),
                "budget_exceeded_rate": round(
                    sum(r["budget_exceeded"] for r in rows) / total, 4),
                "avg_latency_ms": round(sum(r["elapsed_ms"] for r in rows) / total, 1),
            }
            print(f"{strategy}: schema={summary[strategy]['schema_pass_rate']:.2%} "
                  f"cite={summary[strategy]['citation_valid_rate']:.2%} "
                  f"ctx_tokens={summary[strategy]['avg_context_tokens']}")
    finally:
        client.close()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(
        json.dumps({"budget": args.budget, "cases": len(cases), "summary": summary,
                    "details": details}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    lines = ["| 策略 | Schema 通过 | 引用合法 | 双类证据 | 平均上下文 tokens | 平均证据数 | 超预算 | 延迟 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, item in summary.items():
        lines.append(f"| {name} | {item['schema_pass_rate']:.2%} | "
                     f"{item['citation_valid_rate']:.2%} | {item['both_kinds_rate']:.2%} | "
                     f"{item['avg_context_tokens']:.0f} | {item['avg_evidence_sent']:.2f} | "
                     f"{item['budget_exceeded_rate']:.0%} | {item['avg_latency_ms']:.0f} ms |")
    table = "\n".join(lines)
    output.with_suffix(".md").write_text(table + "\n", encoding="utf-8")
    print()
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
