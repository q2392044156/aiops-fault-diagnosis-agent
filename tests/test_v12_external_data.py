import json
from pathlib import Path

from aiops_diag.data.v12_external import (
    assign_splits,
    audit_split_assignments,
    build_hadoop_records,
    build_tracebench_records,
    parse_hadoop_labels,
    tracebench_family,
)


def test_hadoop_adapter_keeps_injection_separate_from_root_cause(tmp_path):
    source = tmp_path / "loghub"
    dataset = source / "Hadoop"
    dataset.mkdir(parents=True)
    labels = """### WordCount
Normal:
+ application_100_0001
Machine down:
+ application_100_0002
"""
    (dataset / "abnormal_label.txt").write_text(labels, encoding="utf-8")
    for number in (1, 2):
        folder = dataset / f"application_100_{number:04d}"
        folder.mkdir()
        (folder / "container.log").write_text(
            "2015-10-17 15:37:56,547 ERROR [main] org.apache.hadoop.hdfs.server.datanode.DataNode: failure\n",
            encoding="utf-8",
        )

    assert len(parse_hadoop_labels(dataset / "abnormal_label.txt")) == 2
    records, audit = build_hadoop_records(dataset, source)
    by_source = {row["source_unit_id"]: row for row in records}
    abnormal = by_source["application_100_0002"]
    assert abnormal["injection_label"] == "machine_down"
    assert abnormal["root_cause_label"] is None
    assert not abnormal["metric_eligibility"]["production_root_cause_ranking"]
    assert abnormal["components"] == ["DataNode"]
    assert audit["source_units"] == 2


def _write_tracebench_scenario(root: Path, name: str):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "trace.csv").write_text(
        "TaskID,Title,NumReports,NumEdges,FirstSeen,LastUpdated,StartTime,EndTime\n"
        "T1,fs -copyToLocal,3,2,2013-11-04 13:54:35,2013-11-04 13:54:36,10,20\n",
        encoding="utf-8",
    )
    (folder / "operation.csv").write_text(
        "OpName,Num,MaxDelay,MinDelay,AverageDelay\nreadBlock,3,10,1,2\n",
        encoding="utf-8",
    )
    (folder / "edge.csv").write_text("TaskID,FatherTID,FatherStartTime,ChildTID\n", encoding="utf-8")
    (folder / "event.csv").write_text(
        "TaskID,TID,OpName,StartTime,EndTime,HostAddress,HostName,Agent,Description\n"
        "T1,S1,readBlock,10,20,10.0.0.1,secret-host,Datanode,Success\n",
        encoding="utf-8",
    )


def test_tracebench_adapter_exports_hashes_without_hosts(tmp_path):
    source = tmp_path / "loghub"
    dataset = source / "HDFS_v3_TraceBench"
    tracebench = dataset / "tracebench"
    tracebench.mkdir(parents=True)
    name = "AN_Net_disconnectDN_r_01DN"
    _write_tracebench_scenario(tracebench, name)

    assert tracebench_family(name) == "AN_Net_disconnectDN"
    records, audit = build_tracebench_records(dataset, source)
    record = records[0]
    assert record["injection_label"] == "network_disconnect_datanode"
    assert record["root_cause_label"] is None
    assert record["observations"]["task_count"] == 1
    assert len(record["evidence_refs"]) == 4
    encoded = json.dumps(record)
    assert "10.0.0.1" not in encoded
    assert "secret-host" not in encoded
    assert audit["normalized_exports_host_or_network_identifiers"] is False


def test_group_isolated_split_is_deterministic():
    records = []
    for dataset, kind, groups in (
        ("loghub_hadoop", "injected_fault", 7),
        ("hdfs_v3_tracebench", "injected_fault", 6),
        ("hdfs_v3_tracebench", "normal", 5),
        ("hdfs_v3_tracebench", "compound", 4),
    ):
        for group in range(groups):
            for member in range(2):
                records.append(
                    {
                        "dataset": dataset,
                        "scenario_kind": kind,
                        "event_id": f"{dataset}-{kind}-{group}-{member}",
                        "source_unit_id": f"source-{group}-{member}",
                        "group_id": f"{dataset}-{kind}-group-{group}",
                    }
                )
    first = assign_splits(records, seed=42)
    second = assign_splits(list(reversed(records)), seed=42)
    assert first == second
    audit = audit_split_assignments(records, first)
    assert audit["passed"]
    assert audit["group_cross_split"] == []
    assert set(audit["split_counts"]) == {"development", "calibration", "independent_test"}
    assert audit["strict_blind_eligible"] is False
