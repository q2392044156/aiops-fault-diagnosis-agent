import json
from datetime import timedelta

import pytest
from drain3.template_miner import TemplateMiner

from aiops_diag.data.common import digest, save, verified_manifest
from aiops_diag.modeling.metrics import classification_metrics, select_threshold
from aiops_diag.modeling.models import _document, _isolation_features, predictions
from aiops_diag.modeling.protocol import _event_clusters, _sample_groups
from aiops_diag.modeling.templates import content, miner_config


def test_event_proxy_clustering_gap_span_and_singletons():
    blocks = {
        "a": {"host_alias": "h", "start": "2000-01-01T00:00:00"},
        "b": {"host_alias": "h", "start": "2000-01-01T00:04:00"},
        "c": {"host_alias": "h", "start": "2000-01-01T00:31:00"},
        "d": {"host_alias": None, "start": "2000-01-01T00:01:00"},
    }
    clusters = _event_clusters(blocks, timedelta(minutes=5), timedelta(minutes=30))
    assert {frozenset(value) for value in clusters} == {
        frozenset({"a", "b"}), frozenset({"c"}), frozenset({"d"})}


def test_sampling_ignores_labels_and_keeps_groups_complete():
    rows = [
        {"block_id": "a", "split": "train", "sampling_group": "g1", "label": 0},
        {"block_id": "b", "split": "train", "sampling_group": "g1", "label": 1},
        {"block_id": "c", "split": "train", "sampling_group": "g2", "label": 0},
    ]
    selected = _sample_groups(rows, 2, "data", 42)
    changed = [dict(row, label=1 - row["label"]) for row in rows]
    assert selected == _sample_groups(changed, 2, "data", 42)
    assert not ({"a", "b"} & selected) or {"a", "b"} <= selected


def test_redaction_and_feature_document_exclude_forbidden_values():
    row = {"level": "ERROR", "component": "DataNode", "message":
           "blk_-123 from 10.1.2.3 pid 456 at /var/lib/hdfs/x 0xCAFE"}
    value = content(row)
    for forbidden in ("blk_-123", "10.1.2.3", "456", "/var/lib/hdfs/x", "0xCAFE"):
        assert forbidden not in value
    assert _document({"template_ids": [2, 4]}) == "T2 T4"


def test_frozen_match_does_not_create_templates():
    cfg = {"parser": {"depth": 4, "max_children": 100}}
    miner = TemplateMiner(None, miner_config(cfg, 0.4))
    miner.add_log_message("INFO A: received item <:NUM:>")
    count = len(miner.drain.clusters)
    assert miner.match("INFO A: totally unseen shape", full_search_strategy="always") is None
    assert len(miner.drain.clusters) == count


def test_metrics_and_constrained_threshold_boundary():
    metrics, curve = select_threshold([1, 0, 1, 0], [0.9, 0.8, 0.7, 0.1], 0.0)
    assert metrics["threshold"] == 0.9
    assert (metrics["tp"], metrics["fp"], metrics["fn"], metrics["tn"]) == (1, 0, 1, 2)
    assert metrics["f1"] == pytest.approx(2 / 3)
    assert metrics["fpr"] == 0.0
    assert curve
    undefined = classification_metrics([1], [0])
    assert undefined["precision"] is None and undefined["fpr"] is None
    unavailable, _ = select_threshold([1, 0], [0.0, 1.0], 0.0)
    assert unavailable["threshold"] is None and not unavailable["useful"]


def test_isolation_features_have_only_declared_numeric_values():
    rows = [{"template_ids": [1, 1, 9], "line_count": 3, "warn_count": 1,
             "error_count": 1, "duration_seconds": 10, "block_id": "secret", "label": 1}]
    matrix = _isolation_features(rows, [1, 2])
    assert matrix.shape == (1, 6)
    assert matrix[0, 0] == 2 and matrix[0, 1] == 0


def test_test_prediction_is_sealed_before_artifact_access():
    with pytest.raises(ValueError, match="sealed"):
        predictions({}, "test")


def test_manifest_tamper_is_rejected(tmp_path):
    artifact = tmp_path / "model.joblib"
    artifact.write_bytes(b"registered")
    save(tmp_path / "manifest.json", {"artifacts": {"model.joblib": digest(artifact)}})
    verified_manifest(tmp_path, "manifest.json")
    artifact.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="changed"):
        verified_manifest(tmp_path, "manifest.json")
