"""模块说明：验证路线 A 的实验编排、incident 合法性与指标计算。"""

import json
from datetime import datetime, timedelta, timezone

from aiops_diag.data.incident_v12 import import_incident, load_incident, validate_incident
from aiops_diag.data.lab import build_incident, sha256_text, write_incident
from aiops_diag.platform.db import Database

import importlib.util
from pathlib import Path

# 变量说明：ROOT 指向仓库根目录。
ROOT = Path(__file__).resolve().parents[1]


# 方法说明：_load 动态加载实验室编排器，避免把 ops 目录变成包。
def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 方法说明：_incident 构造一条带完整时间戳与证据引用的实验事件。
def _incident(tmp_path, code="DN_VOLUME", detected=True):
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(seconds=120)
    logs = "ERROR dfs.DataNode: No space left on device\n"
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "logs" / "case.log").write_text(logs, encoding="utf-8")
    incident_id = "inc_lab_test_0001"
    (tmp_path / incident_id).mkdir(parents=True, exist_ok=True)
    (tmp_path / incident_id / "map.json").write_text(json.dumps({
        "incident_id": incident_id, "diagnosis_id": "dia_test",
        "report_id": "irpt_test"}), encoding="utf-8")
    return build_incident(
        incident_id=incident_id, cluster_alias="cluster_lab_a1",
        fault_code=code, fault_family="dn_volume",
        timestamps={"fault_start": t0, "first_observable_signal": t0 + timedelta(seconds=20),
                    "agent_detected": (t0 + timedelta(seconds=45)) if detected else None,
                    "human_confirmed": t0 + timedelta(seconds=150),
                    "recovered": t0 + timedelta(seconds=140)},
        log_ref={"ref_id": "case", "content_sha256": sha256_text(logs),
                 "redaction_status": "approved_redacted"},
        metric_ref={"ref_id": "case_metrics", "content_sha256": "a" * 64,
                    "redaction_status": "approved_redacted"},
        ticket_ref={"ref_id": "case_ticket", "content_sha256": "b" * 64,
                    "redaction_status": "approved_redacted"},
        cutoff_time=t0 + timedelta(seconds=60))


# 类说明：_Stub 构造只提供所需查询的数据库桩。
class _Stub:
    # 方法说明：__init__ 保存事件记录与报告。
    def __init__(self, record, report):
        self.record = record
        self.report = report

    # 方法说明：all 返回一条 incident_registry 记录。
    def all(self, query, params=()):
        if "incident_registry" in query:
            return [{"incident_id": self.record["incident_id"],
                     "record_json": json.dumps(self.record)}]
        return []

    # 方法说明：one 返回一份诊断报告。
    def one(self, query, params=()):
        if "incident_reports" in query and self.report is not None:
            return {"report_json": json.dumps(self.report)}
        return None


# 方法说明：test_dry_run_generates_valid_incident 验证离线实验产出的记录合法且可导入。
def test_dry_run_generates_valid_incident(tmp_path):
    harness = _load("lab_harness", "ops/lab/harness/run_case.py")
    result = harness.run_case("DN_VOLUME", dry_run=True, case_root=tmp_path)
    incident_path = Path(result["case_dir"]) / "incident.json"
    record = load_incident(incident_path)
    validation = validate_incident(record)
    assert validation["metric_eligibility"]["root_cause_metrics"]["eligible"] is True
    assert record.labels.root_cause_code == "DN_VOLUME"
    assert record.timestamps.fault_start < record.timestamps.first_observable_signal
    assert record.timestamps.first_observable_signal < record.timestamps.recovered
    database = Database(tmp_path / "service.sqlite3")
    database.init()
    imported = import_incident(database, incident_path)
    assert imported["status"] == "ACTIVE"


# 方法说明：test_incident_evidence_hash_matches_file 验证证据哈希与文件一致。
def test_incident_evidence_hash_matches_file(tmp_path):
    record = _incident(tmp_path)
    write_incident(tmp_path / "incident.json", record)
    text = (tmp_path / "logs" / "case.log").read_text(encoding="utf-8")
    ref = record.diagnosis_snapshot.log_refs[0]
    assert ref.content_sha256 == sha256_text(text)


# 方法说明：test_incident_metrics_rank_and_mttd 验证 Top-1 与 MTTD 计算。
def test_incident_metrics_rank_and_mttd(tmp_path):
    evaluator = _load("incident_eval", "ops/scripts/evaluate_incidents.py")
    record = _incident(tmp_path).model_dump(mode="json")
    report = {"hypotheses": [{"component": "DataNode"}, {"component": "NameNode"}]}
    result = evaluator.evaluate(_Stub(record, report), tmp_path)
    summary = result["summary"]
    assert summary["top1"] == 1.0
    assert summary["top3"] == 1.0
    assert summary["mrr"] == 1.0
    assert summary["mttd_seconds"] == 45.0


# 方法说明：test_missing_diagnosis_is_counted_as_excluded 验证没有报告时返回 N/A 而不是 0。
def test_missing_diagnosis_is_counted_as_excluded(tmp_path):
    evaluator = _load("incident_eval_missing", "ops/scripts/evaluate_incidents.py")
    record = _incident(tmp_path).model_dump(mode="json")
    result = evaluator.evaluate(_Stub(record, None), tmp_path)
    assert result["summary"]["top1"] == "N/A"
    assert result["summary"]["exclusion_reasons"] == {"no_diagnosis": 1}

# 方法说明：test_ingest_creates_diagnosis_and_report 验证实验日志可接入并产出报告。
def test_ingest_creates_diagnosis_and_report(tmp_path):
    harness = _load("lab_harness_ingest", "ops/lab/harness/run_case.py")
    ingest_module = _load("lab_ingest", "ops/lab/harness/ingest.py")
    result = harness.run_case("NN_SAFE_MODE", dry_run=True, case_root=tmp_path)
    database_path = tmp_path / "service.sqlite3"
    mapping = ingest_module.ingest(result["case_dir"], database_path)
    assert mapping["diagnosis_id"].startswith("dia_")
    assert mapping["report_id"].startswith("irpt_")
    database = Database(database_path)
    assert database.one("SELECT 1 AS found FROM incident_reports WHERE diagnosis_id=?",
                        (mapping["diagnosis_id"],))["found"] == 1
    assert database.one("SELECT COUNT(*) AS n FROM incident_registry")["n"] == 0

# 方法说明：test_incident_metrics_prefer_root_cause_code 验证代码级匹配优先于组件。
def test_incident_metrics_prefer_root_cause_code(tmp_path):
    evaluator = _load("incident_eval_code", "ops/scripts/evaluate_incidents.py")
    record = _incident(tmp_path).model_dump(mode="json")
    report = {"hypotheses": [{"component": "NameNode", "root_cause_code": "DN_VOLUME"},
                             {"component": "DataNode", "root_cause_code": "DN_HEARTBEAT"}]}
    result = evaluator.evaluate(_Stub(record, report), tmp_path)
    assert result["summary"]["top1"] == 1.0
    assert result["rows"][0]["matched_by"] == "code"
    assert result["rows"][0]["rank"] == 1
