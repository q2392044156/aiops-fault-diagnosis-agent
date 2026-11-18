"""验证上下文预算、压缩策略与报告生成的集成行为。"""

import json

from online.diagnosis.agent import Agent
from online.diagnosis.context_builder import build_context, estimate_tokens

# EVENT 是测试用的事件摘要。
EVENT = {"event_id": "evt_1", "start_time": "2020-01-01T00:00:00+00:00",
         "end_time": "2020-01-01T00:01:00+00:00", "max_anomaly_score": 2.0,
         "threshold": 1.0}
# HYPOTHESES 是测试用的候选原因。
HYPOTHESES = [{"hypothesis_id": "hyp_1", "description": "磁盘写满", "component": "DataNode",
               "support_ids": ["evd_log_1"], "counter_ids": [], "missing_checks": [],
               "support_score": 0.45, "confidence_level": "low"}]
# EVIDENCE 是测试用的证据，包含一条日志与两条知识。
EVIDENCE = [
    {"evidence_id": "evd_log_1", "kind": "log", "excerpt_redacted": "日志 " * 40},
    {"evidence_id": "evd_doc_1", "kind": "doc", "excerpt_redacted": "知识 " * 120},
    {"evidence_id": "evd_doc_2", "kind": "doc", "excerpt_redacted": "补充 " * 120},
]


# _body 构造一份通过 Schema 校验、只引用日志证据的报告。
def _body():
    return {"summary": "s", "observed_facts": ["f"],
            "hypotheses": [{"hypothesis_id": "hyp_1", "description": "磁盘写满",
                            "component": "DataNode", "support_ids": ["evd_log_1"],
                            "counter_ids": [], "missing_checks": [],
                            "support_score": 0.45, "confidence_level": "low"}],
            "checks": [], "missing_information": [], "limitations": ["演示限制"]}


# _Client 返回固定报告，并记录收到的消息。
class _Client:
    # configured 表示该桩客户端视为已配置。
    configured = True

    # __init__ 保存固定返回体。
    def __init__(self, body):
        self.body = body
        self.messages = None

    # complete_json 记录消息并返回固定报告。
    def complete_json(self, messages):
        self.messages = messages
        return self.body, {"input_tokens": 10, "output_tokens": 5,
                           "estimated_cost_cny": 0.0}


# test_estimate_tokens_counts_cjk_and_ascii 验证 token 估算规则。
def test_estimate_tokens_counts_cjk_and_ascii():
    assert estimate_tokens("中文") == 2
    assert estimate_tokens("abcdefgh") == 2
    assert estimate_tokens("") == 1


# test_full_strategy_keeps_every_evidence 验证全量策略不丢证据。
def test_full_strategy_keeps_every_evidence():
    built = build_context(EVENT, HYPOTHESES, EVIDENCE, budget_tokens=100, strategy="full")
    assert built["meta"]["evidence_sent"] == 3
    assert built["meta"]["evidence_dropped"] == 0
    assert built["meta"]["budget_exceeded"] is False


# test_compressed_strategy_respects_budget_and_keeps_kinds 验证预算与类型覆盖。
def test_compressed_strategy_respects_budget_and_keeps_kinds():
    built = build_context(EVENT, HYPOTHESES, EVIDENCE, budget_tokens=400,
                          strategy="compressed")
    kinds = {row["kind"] for row in built["package"]["evidence"]}
    assert built["meta"]["evidence_sent"] == 2
    assert built["meta"]["evidence_dropped"] == 1
    assert kinds == {"log", "doc"}
    assert built["meta"]["budget_exceeded"] is False


# test_compressed_prunes_citations_to_sent_evidence 验证被丢弃的证据不会留在引用里。
def test_compressed_prunes_citations_to_sent_evidence():
    hypotheses = [{"hypothesis_id": "hyp_1", "description": "磁盘写满", "component": "DataNode",
                   "support_ids": ["evd_log_1", "evd_doc_1", "evd_doc_2"],
                   "counter_ids": [], "missing_checks": [], "support_score": 0.45,
                   "confidence_level": "low"}]
    built = build_context(EVENT, hypotheses, EVIDENCE, budget_tokens=400,
                          strategy="compressed")
    sent = {row["evidence_id"] for row in built["package"]["evidence"]}
    support = set(built["package"]["candidate_hypotheses"][0]["support_ids"])
    assert support <= sent
    assert "evd_doc_2" not in support


# test_minimal_strategy_sends_single_evidence 验证最小策略只保留一条。
def test_minimal_strategy_sends_single_evidence():
    built = build_context(EVENT, HYPOTHESES, EVIDENCE, strategy="minimal")
    assert built["meta"]["evidence_sent"] == 1
    assert built["package"]["evidence"][0]["evidence_id"] == "evd_log_1"


# test_duplicate_evidence_is_deduped 验证重复证据被去掉。
def test_duplicate_evidence_is_deduped():
    duplicated = EVIDENCE + [dict(EVIDENCE[1])]
    built = build_context(EVENT, HYPOTHESES, duplicated, budget_tokens=1000,
                          strategy="compressed")
    ids = [row["evidence_id"] for row in built["package"]["evidence"]]
    assert ids.count("evd_doc_1") == 1


# test_tight_budget_flags_exceeded 验证极小预算会被标记为超限。
def test_tight_budget_flags_exceeded():
    built = build_context(EVENT, HYPOTHESES, EVIDENCE, budget_tokens=20,
                          strategy="compressed")
    assert built["meta"]["budget_exceeded"] is True
    assert built["meta"]["evidence_sent"] >= 1


# test_compression_ratio_drops_below_one 验证压缩率小于 1。
def test_compression_ratio_drops_below_one():
    built = build_context(EVENT, HYPOTHESES, EVIDENCE, budget_tokens=400,
                          strategy="compressed")
    assert 0.0 < built["meta"]["compression_ratio"] < 1.0


# test_engine_generate_uses_context_strategy 验证引擎按配置压缩上下文。
def test_engine_generate_uses_context_strategy():
    engine = Agent.__new__(Agent)
    engine.cfg = {"workflow": {"context_strategy": "compressed",
                              "context_budget_tokens": 400}}
    client = _Client(_body())
    engine.client = client
    state = {"errors": []}
    budget = {"llm_calls": 0, "tokens": 0, "active_ms": 0,
              "estimated_cost_cny": 0.0, "max_llm_calls": 3, "max_tokens": 12000,
              "max_active_ms": 120000, "max_tool_calls": 8, "tool_calls": 0}
    body, status = engine._generate({"mode": "auto"}, state, budget, EVENT,
                                    HYPOTHESES, EVIDENCE)
    assert status == "EVIDENCE_SUPPORTED"
    assert state["context"]["strategy"] == "compressed"
    package = json.loads(client.messages[1]["content"])
    assert len(package["evidence"]) == 2
