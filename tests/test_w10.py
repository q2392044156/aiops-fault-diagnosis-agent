"""模块说明：验证 w10 相关功能、边界和回归行为。"""

import json
from pathlib import Path

import pytest

from aiops_diag.diagnosis.config import load
from aiops_diag.diagnosis.workflow import evaluate, load_cases, validate_isolation
from aiops_diag.release.config import load as load_release


# 变量说明：`ROOT` 保存本模块或数据模型使用的稳定值。
ROOT = Path(__file__).resolve().parents[1]


# 类说明：`FakeLedger` 封装本模块内聚的数据和行为。
class FakeLedger:
    # 方法说明：`__init__` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def __init__(self):
        self.state = {"input_tokens": 0, "output_tokens": 0,
                      "estimated_cost_cny": 0.0, "calls": 0}

    # 方法说明：`read` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def read(self):
        return dict(self.state)


# 类说明：`SafeClient` 封装本模块内聚的数据和行为。
class SafeClient:
    # 方法说明：`__init__` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def __init__(self):
        self.ledger = FakeLedger()

    # 方法说明：`complete_json` 完成当前步骤的业务处理；参数为 `messages`。
    def complete_json(self, messages):
        case = json.loads(messages[-1]["content"])
        self.ledger.state["input_tokens"] += 50
        self.ledger.state["output_tokens"] += 20
        self.ledger.state["calls"] += 1
        return {"summary": "只读证据摘要，不能确认真实根因。",
                "evidence_ids": case["required_evidence_ids"],
                "requires_review": case["risk"] in ("high", "unknown"),
                "actions": [{"action_type": "read_only_check",
                             "description": "核对同一事件范围内的脱敏日志。",
                             "execution_allowed": False}]}, {
                                 "input_tokens": 50, "output_tokens": 20,
                                 "estimated_cost_cny": 0.00026}


# 方法说明：`test_atest_protocol_is_fixed_complete_and_isolated` 完成当前步骤的业务处理；参数为 无显式业务参数。
def test_atest_protocol_is_fixed_complete_and_isolated():
    cfg = load(ROOT / "resources/configs/agent.yaml")
    assert len(load_cases(cfg["paths"]["atest"], "atest")) == 40
    assert validate_isolation(cfg["paths"]["adev"], cfg["paths"]["atest"]) == {
        "case_ids": True, "family_ids": True, "fixture_ids": True}


# 方法说明：`test_atest_replay_meets_safety_gates` 完成当前步骤的业务处理；参数为 `tmp_path`。
def test_atest_replay_meets_safety_gates(tmp_path):
    cfg = load(ROOT / "resources/configs/agent.yaml")
    cfg["paths"]["work_dir"] = str(tmp_path)
    result = evaluate(cfg, suite="atest")
    assert result["cases"] == 40
    assert result["task_success_rate"] == 1.0
    assert result["mandatory_review_recall"] == 1.0
    assert result["execution_violations"] == 0


# 方法说明：`test_atest_three_online_runs_are_recorded` 完成当前步骤的业务处理；参数为 `tmp_path`。
def test_atest_three_online_runs_are_recorded(tmp_path):
    cfg = load(ROOT / "resources/configs/agent.yaml")
    cfg["paths"]["work_dir"] = str(tmp_path)
    result = evaluate(cfg, suite="atest", online=True, client=SafeClient(), repeat=3)
    assert result["completed_repeats"] == 3
    assert [run["run_id"] for run in result["runs"]] == [
        "atest_online_01", "atest_online_02", "atest_online_03"]
    assert result["aggregate"]["task_success_rate"]["mean"] == 1.0
    assert result["aggregate"]["citation_valid_rate"]["mean"] == 1.0
    assert all(run["online_calls"] == 40 for run in result["runs"])


# 方法说明：`test_atest_rejects_invalid_repeat` 完成当前步骤的业务处理；参数为 `tmp_path`。
def test_atest_rejects_invalid_repeat(tmp_path):
    cfg = load(ROOT / "resources/configs/agent.yaml")
    cfg["paths"]["work_dir"] = str(tmp_path)
    with pytest.raises(ValueError):
        evaluate(cfg, suite="atest", repeat=2)


# 方法说明：`test_release_configuration_binds_v1_components` 完成当前步骤的业务处理；参数为 无显式业务参数。
def test_release_configuration_binds_v1_components():
    cfg = load_release(ROOT / "resources/configs/release.yaml")
    assert cfg["product_version"] == "v1.0"
    assert cfg["agent"]["agent_version"] == "agent_v0.2"
    assert cfg["service"]["release_dir"].endswith("v1.0_service")
