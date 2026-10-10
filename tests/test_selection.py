import numpy as np
import pytest
import torch
from sklearn.metrics import average_precision_score

from aiops_diag.data.common import digest, save
from aiops_diag.modeling.lstm_model import LSTMClassifier, collate_sequences
from aiops_diag.selection.workflow import (_stage, _variant_rows, _weighted_ap,
                                           paired_bootstrap)


def test_weighted_ap_matches_sklearn():
    labels = np.asarray([1, 0, 1, 0, 1], dtype=np.int8)
    scores = np.asarray([0.9, 0.7, 0.7, 0.2, 0.1], dtype=np.float64)
    weights = np.asarray([2, 1, 3, 2, 1], dtype=np.float64)
    assert _weighted_ap(labels, scores, weights) == pytest.approx(
        average_precision_score(labels, scores, sample_weight=weights))


def test_group_paired_bootstrap_is_deterministic():
    rows = []
    values = [
        ("a", "g1", 1, 0.9, 1, 0.8, 1),
        ("b", "g1", 0, 0.6, 1, 0.2, 0),
        ("c", "g2", 1, 0.4, 0, 0.7, 1),
        ("d", "g3", 0, 0.1, 0, 0.1, 0),
    ]
    for block, group, label, lr_score, lr_prediction, nn_score, nn_prediction in values:
        rows.append({"model_id": "logistic_regression", "block_id": block,
                     "sampling_group": group, "label": label,
                     "anomaly_score": lr_score, "prediction": lr_prediction})
        rows.append({"model_id": "lstm_seed_42", "block_id": block,
                     "sampling_group": group, "label": label,
                     "anomaly_score": nn_score, "prediction": nn_prediction})
    cfg = {"bootstrap": {"seed": 7, "replicates": 50,
                          "method": "poisson_group_paired"}}
    first = paired_bootstrap(rows, cfg)
    second = paired_bootstrap(rows, cfg)
    assert first == second
    assert first["valid_replicates"] <= 50
    assert first["delta_f1"]["mean"] > 0


def test_shuffle_ablation_is_stable_and_preserves_membership():
    rows = [{"block_id": "a", "template_ids": [1, 2, 3, 4],
             "gap_seconds": [0.0, 1.0, 2.0, 3.0], "label": 1}]
    cfg = {"ablation": {"shuffle_seed": 704}}
    first = _variant_rows(rows, "no_order_no_gap", cfg)
    second = _variant_rows(rows, "no_order_no_gap", cfg)
    assert first == second
    assert sorted(first[0]["template_ids"]) == [1, 2, 3, 4]
    assert first[0]["gap_seconds"] == [0.0] * 4
    assert first[0]["label"] == 1 and first[0]["block_id"] == "a"


def test_lstm_can_remove_safe_feature_branch():
    item = {"block_id": "a", "template_ids": [1, 2], "gaps": [0.0, 1.0],
            "session_features": [100.0, 200.0, 0.5, 0.5], "label": 1.0,
            "first_log_id": "f:1", "last_log_id": "f:2"}
    batch = collate_sequences([item])
    model = LSTMClassifier(4, embedding_dim=4, hidden_dim=4, dropout=0.0,
                           session_feature_count=0).eval()
    with torch.inference_mode():
        score = model(batch["template_ids"], batch["gaps"], batch["mask"],
                      batch["chunk_valid"], batch["session_features"])
    assert score.shape == (1,) and torch.isfinite(score).all()


def test_stage_manifest_tamper_is_rejected(tmp_path):
    artifact = tmp_path / "result.json"
    artifact.write_text("{}", encoding="utf-8")
    save(tmp_path / "manifest.json", {"artifacts": {"result.json": digest(artifact)}})
    save(tmp_path / "registry.json", {
        "artifacts": {"manifest.json": digest(tmp_path / "manifest.json")}})
    _stage(tmp_path, "manifest.json")
    save(tmp_path / "manifest.json", {"artifacts": {"result.json": digest(artifact)},
                                      "changed": True})
    with pytest.raises(ValueError, match="changed"):
        _stage(tmp_path, "manifest.json")
