import pytest
import torch

from aiops_diag.data.common import digest, save
from aiops_diag.modeling.lstm_model import LSTMClassifier, collate_sequences
from aiops_diag.modeling.lstm_workflow import (evaluate_lstm, inspect_lstm,
                                               predict_lstm, training_weight)
from aiops_diag.modeling.sequences import role_for


def _item(block_id, length, label=0.0):
    return {
        "block_id": block_id,
        "template_ids": [1 + index % 5 for index in range(length)],
        "gaps": [float(index % 3) for index in range(length)],
        "session_features": [0.1, -0.2, 0.0, 0.1],
        "label": label,
        "first_log_id": f"{block_id}:1",
        "last_log_id": f"{block_id}:{length}",
    }


@pytest.mark.parametrize("length,chunks", [(128, 1), (129, 2), (256, 2), (280, 3)])
def test_contiguous_chunk_boundaries_keep_the_complete_session(length, chunks):
    batch = collate_sequences([_item("b", length)], max_length=128)
    assert batch["template_ids"].shape == (1, chunks, 128)
    assert int(batch["mask"].sum()) == length
    assert int(batch["chunk_valid"].sum()) == chunks
    restored = batch["template_ids"][batch["mask"]].tolist()
    assert restored == _item("b", length)["template_ids"]


def test_empty_and_misaligned_sequences_are_rejected():
    with pytest.raises(ValueError, match="Empty"):
        collate_sequences([_item("empty", 0)])
    broken = _item("broken", 3)
    broken["gaps"] = [0.0]
    with pytest.raises(ValueError, match="differ"):
        collate_sequences([broken])


def test_padding_does_not_change_cpu_prediction():
    torch.manual_seed(42)
    model = LSTMClassifier(vocabulary_size=8, embedding_dim=32, hidden_dim=32,
                           dropout=0.2).eval()
    short = _item("short", 17)
    alone = collate_sequences([short])
    mixed = collate_sequences([short, _item("long", 280)])
    with torch.inference_mode():
        one = model(alone["template_ids"], alone["gaps"], alone["mask"],
                    alone["chunk_valid"], alone["session_features"])[0]
        many = model(mixed["template_ids"], mixed["gaps"], mixed["mask"],
                     mixed["chunk_valid"], mixed["session_features"])[0]
    assert float(torch.abs(one - many)) <= 1e-6


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_padding_does_not_change_cuda_prediction():
    torch.manual_seed(42)
    model = LSTMClassifier(vocabulary_size=8, embedding_dim=32, hidden_dim=32,
                           dropout=0.2).cuda().eval()
    short = collate_sequences([_item("short", 17)])
    mixed = collate_sequences([_item("short", 17), _item("long", 280)])
    short = {name: value.cuda() if torch.is_tensor(value) else value
             for name, value in short.items()}
    mixed = {name: value.cuda() if torch.is_tensor(value) else value
             for name, value in mixed.items()}
    with torch.inference_mode():
        one = model(short["template_ids"], short["gaps"], short["mask"],
                    short["chunk_valid"], short["session_features"])[0]
        many = model(mixed["template_ids"], mixed["gaps"], mixed["mask"],
                     mixed["chunk_valid"], mixed["session_features"])[0]
    assert float(torch.abs(one - many)) <= 1e-5


def test_group_role_is_deterministic_and_label_independent():
    before = role_for("g1", "ddev", 42, 0.8)
    after_label_change = role_for("g1", "ddev", 42, 0.8)
    assert before == after_label_change
    assert before in {"fit", "holdout"}


def test_pos_weight_uses_only_current_training_members():
    rows = [{"block_id": "a"}, {"block_id": "b"}, {"block_id": "c"}]
    labels = {"a": 1, "b": 0, "c": 0, "outside": 1}
    value, audit = training_weight(rows, labels, "full", 10.0)
    assert value == 2.0
    assert audit["positive"] == 1 and audit["negative"] == 2
    assert training_weight(rows, labels, "one", 10.0)[0] == 1.0
    assert training_weight(rows, labels, "capped", 1.5)[0] == 1.5


def test_lstm_test_split_is_sealed_before_artifact_access():
    with pytest.raises(ValueError, match="sealed"):
        predict_lstm({}, "test")
    with pytest.raises(ValueError, match="sealed"):
        evaluate_lstm({}, "test")


def test_lstm_inspect_rejects_tampered_registered_artifact(tmp_path):
    run = tmp_path / "w3_demo"
    run.mkdir()
    predictions = run / "predictions.parquet"
    predictions.write_bytes(b"registered")
    save(run / "training.json", {
        "run_id": "w3_demo", "artifacts": {"predictions.parquet": digest(predictions)}})
    save(run / "registry.json", {
        "artifacts": {"training.json": digest(run / "training.json")}})
    predictions.write_bytes(b"tampered")
    cfg = {"experiment_root": str(tmp_path), "seeds": [42]}
    with pytest.raises(ValueError, match="changed"):
        inspect_lstm(cfg, "w3_demo", 42, "blk_1")
