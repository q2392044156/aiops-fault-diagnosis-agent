"""Exercise the LangChain summary path once with the configured provider."""

import argparse
import json
import os
from pathlib import Path

from aiops_diag.agent_v11.engine import AgentEngine
from aiops_diag.framework_v12.report_chain import CandidateSummaryChain
from aiops_diag.rag.client import BudgetLedger, DeepSeekClient
from aiops_diag.rag.config import load


def load_local_secrets(path):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        name, value = text.split("=", 1)
        if name in {"DEEPSEEK_API_KEY", "DEEPSEEK_TRACKING_ID"}:
            os.environ.setdefault(name, value.strip().strip('"').strip("'"))


def run(config_path, env_path, output):
    load_local_secrets(env_path)
    cfg = load(config_path)
    ledger_path = output.with_suffix(".budget.json")
    ledger = BudgetLedger(ledger_path, cfg["budget"])
    before = ledger.read()
    client = DeepSeekClient(cfg, ledger=ledger)
    if not client.configured:
        raise RuntimeError("DeepSeek API key is not configured")
    try:
        engine = object.__new__(AgentEngine)
        engine.client = client
        engine.summary_chain = CandidateSummaryChain()
        budget = {"max_tool_calls": 8, "max_llm_calls": 3, "max_tokens": 12000,
                  "max_active_ms": 120000, "tool_calls": 0, "llm_calls": 0,
                  "tokens": 0, "active_ms": 0, "estimated_cost_cny": 0.0}
        evidence = [
            {"evidence_id": "ev_log_smoke", "kind": "log",
             "excerpt_redacted": "Synthetic NameNode warning for framework validation."},
            {"evidence_id": "ev_doc_smoke", "kind": "doc",
             "excerpt_redacted": "Synthetic read-only runbook evidence."},
        ]
        hypotheses = [{
            "hypothesis_id": "hyp_smoke",
            "description": "待验证候选：日志观测与只读知识证据存在关联。",
            "component": "NameNode",
            "support_ids": ["ev_log_smoke", "ev_doc_smoke"],
            "counter_ids": [],
            "missing_checks": ["需要人工结合独立运行指标确认"],
            "support_score": 0.6,
            "confidence_level": "medium",
        }]
        state = {"errors": []}
        body, status = engine._generate(
            {"mode": "auto"}, state, budget,
            {"event_id": "evt_framework_smoke", "start_time": "2026-10-20T00:00:00",
             "end_time": "2026-10-20T00:01:00", "max_anomaly_score": 5.0,
             "threshold": 4.0}, hypotheses, evidence)
    finally:
        client.close()
    after = ledger.read()
    result = {
        "schema_version": 1,
        "status": "FRAMEWORK_LANGCHAIN_ONLINE_SMOKE",
        "diagnosis_status": status,
        "summary_schema_valid": bool(body.summary),
        "model_controlled_citation_count": 0,
        "execution_allowed_count": sum(bool(item.execution_allowed) for item in body.checks),
        "agent_budget": budget,
        "errors": state["errors"],
        "provider_usage_delta": {
            name: round(after[name] - before[name], 8)
            for name in ("input_tokens", "output_tokens", "estimated_cost_cny", "calls")
        },
        "synthetic_input": True,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/rag.yaml"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    print(json.dumps(run(options.config, options.env, options.output),
                     ensure_ascii=False, indent=2))
