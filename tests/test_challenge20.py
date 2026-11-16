"""模块说明：验证 challenge20 的数据构造、标签隔离与评测解析。"""

import json
from pathlib import Path

from ops.scripts.build_challenge20 import paraphrase
from ops.scripts.evaluate_challenge20 import _report_codes

# 变量说明：ROOT 是仓库根目录。
ROOT = Path(__file__).resolve().parents[1]
# 变量说明：CHALLENGE 是挑战集资源目录。
CHALLENGE = ROOT / "resources" / "evaluation" / "challenge20"


# 方法说明：读入挑战集清单。
def _manifest():
    return json.loads((CHALLENGE / "manifest.json").read_text(encoding="utf-8"))


# 方法说明：验证 20 例、四组均衡、三类构成和案例文件完整。
def test_manifest_has_four_balanced_groups_and_complete_cases():
    manifest = _manifest()
    assert manifest["case_count"] == 20
    assert manifest["groups"] == {"format_time": 5, "evidence_drop": 5,
                                  "paraphrase": 5, "paraphrase_distractor": 5}
    assert manifest["classes"] == {"volume": 7, "heartbeat": 7, "safe_mode": 6}
    for case in manifest["cases"]:
        root = ROOT / case["path"]
        assert (root / "incident.json").is_file()
        assert (root / "challenge.json").is_file()
        assert list((root / "evidence" / "logs").glob("*"))
        meta = json.loads((root / "challenge.json").read_text(encoding="utf-8"))
        assert meta["synthetic"] is True and meta["not_independent"] is True
        assert meta["group"] == case["group"]
        incident = json.loads((root / "incident.json").read_text(encoding="utf-8"))
        assert incident["labels"]["root_cause_code"] == case["root_cause_code"]
        assert incident["incident_id"] == case["case_id"]


# 方法说明：验证挑战源案例没有进入 unified4，避免测试泄漏。
def test_source_cases_are_holdout_from_unified4():
    unified = json.loads((ROOT / "resources" / "evaluation" / "unified4" /
                          "manifest.json").read_text(encoding="utf-8"))
    used = {case["case_id"] for case in unified["cases"]}
    assert not ({case["original_case"] for case in _manifest()["cases"]} & used)


# 方法说明：验证同义改写移除了原始关键词，但保留故障语义位置。
def test_paraphrase_removes_original_keyword_signals():
    assert paraphrase("Lost DataNode datanode2") == "DataNode datanode2 missed its liveness deadline"
    assert "No space left on device" not in paraphrase("No space left on device")
    assert "Safe mode is ON." not in paraphrase("Safe mode is ON.")
    manifest = _manifest()
    for case in manifest["cases"]:
        if case["group"] != "paraphrase":
            continue
        log = next((ROOT / case["path"] / "evidence" / "logs").glob("*"))
        text = log.read_text(encoding="utf-8")
        assert "Lost DataNode" not in text
        assert "No space left on device" not in text
        assert "Entering safe mode" not in text
        assert "Safe mode is ON." not in text


# 方法说明：验证报告解析按候选顺序返回根因码和诊断模式。
def test_report_codes_keep_hypothesis_order():
    raw = json.dumps({"diagnosis_status": "DEGRADED_TEMPLATE", "hypotheses": [
        {"root_cause_code": "DN_VOLUME"}, {"root_cause_code": "DN_HEARTBEAT"}]})
    assert _report_codes(raw) == (["DN_VOLUME", "DN_HEARTBEAT"], "DEGRADED_TEMPLATE")
    assert _report_codes(None) == ([], None)
