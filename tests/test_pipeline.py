import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from aiops_diag.data.parser import parse
from aiops_diag.data.pipeline import build, split, subset, trace
from aiops_diag.data.audit import audit
from aiops_diag.data.common import digest


@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b""])
def test_parser(ending):
    raw = b"081109 203518 143 INFO dfs.DataNode: blk_-1 blk_2 blk_-1" + ending
    r = parse(raw, 1, 0, "abc")
    assert r["session_ids"] == ["blk_-1", "blk_2"]
    assert r["parse_status"] == "ok"
    assert r["timestamp_utc"] is None
    assert r["byte_length"] == len(raw)


@pytest.mark.parametrize("raw,status", [(b"bad blk_1", "format_error"),
    (b"081332 203518 1 INFO x: blk_1", "time_error"), (b"\xff blk_1", "decode_error")])
def test_bad(raw, status):
    assert parse(raw, 1, 0, "x")["parse_status"] == status


@pytest.fixture
def dataset(tmp_path):
    raw = tmp_path / "raw"; raw.mkdir()
    lines = ["081101 000000 1 INFO x: blk_0",
             "081101 010000 1 INFO x: blk_1 blk_2",
             "081101 020000 1 INFO x: blk_2 blk_3",
             "081101 030000 1 INFO x: blk_4",
             "081101 060000 1 INFO x: blk_5",
             "081101 070000 1 INFO x: blk_6",
             "081101 080000 1 INFO x: blk_7",
             "081101 100000 1 INFO x: blk_8"]
    (raw / "HDFS.log").write_text("\n".join(lines), encoding="utf-8")
    (raw / "anomaly_label.csv").write_text("BlockId,Label\n" + "".join(f"blk_{i},Normal\n" for i in range(9)))
    return dict(raw_dir=str(raw), output_dir=str(tmp_path / "out"), dataset="synthetic", batch_size=3,
                min_free_gb=0, embargo_seconds=600, seed=42, target_blocks=4, max_lines=10)


def test_end_to_end(dataset):
    folder = build(dataset); split(dataset); subset(dataset)
    report = audit(dataset)
    assert report["data_checks_pass"]
    assert report["cross_split_shared_lines"] == 0
    rows = pq.read_table(folder / "splits.parquet").to_pylist()
    by_id = {r["block_id"]: r for r in rows}
    assert len({by_id[f"blk_{i}"]["group_id"] for i in (1, 2, 3)}) == 1
    assert by_id["blk_5"]["reason"] == "embargo"
    assert by_id["blk_7"]["reason"] == "embargo"
    first = json.loads((folder / "subset.json").read_text())
    subset(dataset)
    assert json.loads((folder / "subset.json").read_text()) == first
    h = digest(Path(dataset["raw_dir"]) / "HDFS.log")
    assert trace(dataset, h + ":8")["verified"]
    feature_hash = digest(folder / "logs.parquet")
    labels = Path(dataset["raw_dir"]) / "anomaly_label.csv"
    labels.write_text(labels.read_text().replace("Normal", "Anomaly"))
    assert build(dataset) == folder
    split(dataset); subset(dataset)
    assert digest(folder / "logs.parquet") == feature_hash
    assert json.loads((folder / "subset.json").read_text()) == first
    assert "label" not in pq.read_schema(folder / "logs.parquet").names
    assert audit(dataset)["label_counts"] == {"Anomaly": 9}


def test_crossing_group(dataset):
    path = Path(dataset["raw_dir"]) / "HDFS.log"
    path.write_text(path.read_text() + "\n081101 090000 1 INFO x: blk_3")
    folder = build(dataset); split(dataset)
    rows = pq.read_table(folder / "splits.parquet").to_pylist()
    assert all(r["reason"] == "boundary_excluded" for r in rows if r["block_id"] in {"blk_1", "blk_2", "blk_3"})


def test_bad_session_and_budget(dataset):
    path = Path(dataset["raw_dir"]) / "HDFS.log"
    path.write_bytes(path.read_bytes() + b"\nbroken blk_3\n081101 040000 1 INFO x: no block\n")
    dataset["max_lines"] = 1
    folder = build(dataset); split(dataset); subset(dataset)
    rows = pq.read_table(folder / "splits.parquet").to_pylist()
    assert all(r["reason"] == "invalid_session" for r in rows if r["block_id"] in {"blk_1", "blk_2", "blk_3"})
    report = audit(dataset)
    assert report["counts"]["format_error"] == 1
    assert report["counts"]["no_block"] == 1
    assert report["dev"]["lines"] <= 1


def test_tamper_rejected(dataset):
    folder = build(dataset)
    with (folder / "logs.parquet").open("ab") as f:
        f.write(b"corrupt")
    with pytest.raises(ValueError, match="Artifact changed"):
        split(dataset)


def test_relocated_rebuild(dataset, tmp_path):
    import shutil
    folder = build(dataset); split(dataset); subset(dataset)
    original = json.loads((folder / "subset.json").read_text())
    moved = dict(dataset)
    moved["raw_dir"] = str(tmp_path / "moved_raw")
    moved["output_dir"] = str(tmp_path / "moved_out")
    shutil.copytree(dataset["raw_dir"], moved["raw_dir"])
    other = build(moved); split(moved); subset(moved)
    assert folder.name == other.name
    assert json.loads((other / "subset.json").read_text()) == original


def test_duplicate_label_rejected(dataset):
    build(dataset); split(dataset); subset(dataset)
    with (Path(dataset["raw_dir"]) / "anomaly_label.csv").open("a") as f:
        f.write("blk_1,Anomaly\n")
    with pytest.raises(ValueError, match="Audit checks failed"):
        audit(dataset)
