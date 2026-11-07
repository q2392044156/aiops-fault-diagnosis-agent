"""模块说明：验证模板新颖度检测器。"""

from aiops_diag.detection.source_detector import TemplateNoveltyDetector


# 方法说明：构造一行日志。
def _row(message="hello", level="INFO"):
    return {"level": level, "component": "DataNode", "message": message}


# 方法说明：返回与检测器一致的模板文本。
def _text_for(message, level):
    from aiops_diag.detection.source_detector import _text
    return _text(_row(message, level))


# 方法说明：验证正常模板不报警、新模板报警。
def test_novelty_detector_separates_templates():
    detector = TemplateNoveltyDetector(0.05).fit([[_row("started"), _row("ready")]])
    assert detector.score([_row("started")]) == 0.0
    assert detector.decide([_row("started")])["decision"] == "REJECT"
    novel = [_row("No space left on device", "ERROR")]
    assert detector.score(novel) == 1.0
    assert detector.decide(novel)["decision"] == "PASS"


# 方法说明：验证见过的 ERROR 仍然通过门禁。
def test_seen_error_always_passes():
    detector = TemplateNoveltyDetector(0.05).fit([[_row("known error", "ERROR")]])
    decision = detector.decide([_row("known error", "ERROR")])
    assert decision["decision"] == "PASS"
    assert decision["reason"] == "error_present"


# 方法说明：验证已审核的良性错误可被白名单抑制。
def test_benign_error_can_be_allowlisted():
    benign = _text_for("known error", "ERROR")
    detector = TemplateNoveltyDetector(0.05, benign_errors=[benign]).fit(
        [[_row("known error", "ERROR")]])
    decision = detector.decide([_row("known error", "ERROR")])
    assert decision["decision"] == "REJECT"


# 方法说明：验证频繁已知 WARN 被拒绝。
def test_known_warn_within_baseline_rejected():
    detector = TemplateNoveltyDetector(0.05).fit([[_row("known warn", "WARN")]])
    decision = detector.decide([_row("known warn", "WARN")])
    assert decision["decision"] == "REJECT"
    assert decision["reason"] == "known_warn"


# 方法说明：验证 WARN 频次超过正常基线时通过。
def test_warn_frequency_above_baseline_passes():
    detector = TemplateNoveltyDetector(0.05).fit([[_row("known warn", "WARN")]])
    decision = detector.decide([_row("known warn", "WARN"), _row("known warn", "WARN")])
    assert decision["decision"] == "PASS"
    assert decision["reason"] == "warn_frequency"


# 方法说明：验证检测器可保存与恢复。
def test_novelty_detector_save_and_load(tmp_path):
    detector = TemplateNoveltyDetector(0.05).fit([[_row("started")]])
    path = detector.save(tmp_path / "detector.json")
    loaded = TemplateNoveltyDetector.load(path)
    assert loaded.threshold == detector.threshold
    assert loaded.templates == detector.templates
