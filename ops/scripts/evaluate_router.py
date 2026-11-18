"""运行工具路由对照实验（确定性 / 受控 function calling / 无约束）。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# ROOT 指向仓库根目录，便于脚本在任意工作目录运行。
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from evaluation.router import FREE_PROMPT, markdown, score
from online.diagnosis.tool_router import TOOL_ROUTER_PROMPT, ToolRouter
from online.knowledge.generation.client import BudgetLedger, DeepSeekClient

# ALLOWLIST 是本次实验允许的三个只读工具。
ALLOWLIST = ["query_metrics", "search_similar_incidents"]
# BUDGET 限制实验的总花费，避免脚本跑飞。
BUDGET = {"max_total_tokens": 500000, "max_cost_cny": 5.0, "max_input_tokens_per_call": 10000,
          "input_cny_per_million": 2.0, "output_cny_per_million": 8.0}


# _load_env 读取 .env，已存在的环境变量优先。
def _load_env(path):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, _, value = line.partition("=")
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


# _client 构造带预算账本的 DeepSeek 客户端。
def _client(args):
    cfg = {
        "provider": {
            "name": "deepseek", "base_url": "https://api.deepseek.com",
            "model": args.model, "api_key_env": "DEEPSEEK_API_KEY",
            "api_key_file_env": "DEEPSEEK_API_KEY_FILE",
            "tracking_id_env": "DEEPSEEK_TRACKING_ID",
            "tracking_id_file_env": "DEEPSEEK_TRACKING_ID_FILE",
            "timeout_seconds": 30, "overall_timeout_seconds": 45,
            "max_tokens": 400, "temperature": 0,
        },
        "budget": BUDGET,
        "paths": {},
    }
    ledger = BudgetLedger(ROOT / "runtime" / "router_budget.json", BUDGET)
    return DeepSeekClient(cfg, ledger=ledger)


# _deterministic 表示不调用任何可选工具的基线。
def _deterministic(case, client, router):
    return {"case_id": case["case_id"], "expected": case["expected_tools"],
            "predicted": [], "usage": {}, "elapsed_ms": 0.0, "policy": "fixed"}


# _constrained 走 function calling + 白名单 + Schema 校验。
def _constrained(case, client, router):
    # invoke 把工具定义交给客户端，返回模型的工具调用。
    def invoke(messages, tools):
        return client.complete_tool_calls(messages, tools)

    outcome = router.route(case["summary"], invoke)
    return {"case_id": case["case_id"], "expected": case["expected_tools"],
            "predicted": outcome["names"], "usage": outcome["usage"],
            "elapsed_ms": outcome["elapsed_ms"], "policy": outcome["policy"],
            "blocked": outcome["blocked"]}


# _rules 使用与受控路由相同的规则提示，但只返回工具名、不做校验。
def _rules(case, client, router):
    system = TOOL_ROUTER_PROMPT.format(max_tools=2) + \
        '只输出严格 JSON：{"next_tools": []}，不要输出工具参数。'
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": json.dumps(case["summary"], ensure_ascii=False)}]
    started = time.perf_counter()
    try:
        value, usage = client.complete_json(messages)
        names = value.get("next_tools") if isinstance(value, dict) else []
        predicted = [str(name) for name in (names or [])][:3]
        policy = "model"
    except Exception as exc:
        predicted, usage, policy = [], {}, f"error:{type(exc).__name__}"
    return {"case_id": case["case_id"], "expected": case["expected_tools"],
            "predicted": predicted, "usage": usage,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "policy": policy}


# _free 让模型自由输出工具名，不做白名单、Schema 与数量校验。
def _free(case, client, router):
    messages = [{"role": "system", "content": FREE_PROMPT},
                {"role": "user", "content": json.dumps(case["summary"], ensure_ascii=False)}]
    started = time.perf_counter()
    try:
        value, usage = client.complete_json(messages)
        names = value.get("next_tools") if isinstance(value, dict) else []
        predicted = [str(name) for name in (names or [])][:3]
        policy = "model"
    except Exception as exc:  # 解析失败按空选择计
        predicted, usage, policy = [], {}, f"error:{type(exc).__name__}"
    return {"case_id": case["case_id"], "expected": case["expected_tools"],
            "predicted": predicted, "usage": usage,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "policy": policy}


# main 依次运行三种模式并写出 JSON 与 Markdown 结果。
def main(argv=None):
    parser = argparse.ArgumentParser(description="Router comparison experiment")
    parser.add_argument("--cases", default=str(ROOT / "resources/evaluation/router/cases.jsonl"))
    parser.add_argument("--output", default=str(ROOT / "resources/evaluation/router/result"))
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--modes", default="deterministic,free,rules,constrained")
    args = parser.parse_args(argv)

    _load_env(Path(args.env_file))
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY is not configured")
        return 2

    cases = [json.loads(line) for line in Path(args.cases).read_text(
        encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        cases = cases[: args.limit]
    client = _client(args)
    router = ToolRouter(ALLOWLIST, max_tools=2)
    runners = {"deterministic": _deterministic, "constrained": _constrained,
               "free": _free, "rules": _rules}
    selected = [name.strip() for name in args.modes.split(",") if name.strip()]

    results, details = {}, {}
    try:
        for mode in selected:
            rows = [runners[mode](case, client, router) for case in cases]
            details[mode] = rows
            results[mode] = score(rows)
            print(f"{mode}: exact={results[mode]['exact_match_rate']:.2%} "
                  f"f1={results[mode]['f1']:.2f} tokens={results[mode]['total_tokens']}")
    finally:
        client.close()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"model": args.model, "cases": len(cases), "summary": results,
               "details": details}
    (output.with_suffix(".json")).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    table = markdown(results)
    (output.with_suffix(".md")).write_text(table + "\n", encoding="utf-8")
    print()
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
