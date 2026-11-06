"""模块说明：验证模板新颖度检测器。"""

from aiops_diag.detection.source_detector import TemplateNoveltyDetector


# 方法说明：构造一行日志。
def _row(message="hello", level="INFO"):
    return {"level": level, "component": "DataNode", "message": message}


# 方法说明：验证正常模板不报警、新模板报警。
def test_novelty_detector_separates_templates():
    detector = TemplateNoveltyDetector(0.05).fit([[_row("started"), _row("ready")]])
    assert detector.score([_row("started")]) == 0.0
    assert detector.decide([_row("started")])["decision"] == "REJECT"
    novel = [_row("No space left on device", "ERROR")]
    assert detector.score(novel) == 1.0
    assert detector.decide(novel)["decision"] == "PASS"


# 方法说明：验证检测器可保存与恢复。
def test_novelty_detector_save_and_load(tmp_path):
    detector = TemplateNoveltyDetector(0.05).fit([[_row("started")]])
    path = detector.save(tmp_path / "detector.json")
    loaded = TemplateNoveltyDetector.load(path)
    assert loaded.threshold == detector.threshold
    assert loaded.templates == detector.templates
