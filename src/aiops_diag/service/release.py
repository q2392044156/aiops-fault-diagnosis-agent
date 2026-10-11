import json
from pathlib import Path

import joblib
import numpy as np
from drain3.file_persistence import FilePersistence
from drain3.template_miner import TemplateMiner

from aiops_diag.data.common import digest, key, save, verified_manifest
from aiops_diag.modeling.templates import content, miner_config


SERVICE_RELEASE = "v0.2_lr"


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _w2_run(cfg, templates):
    run_id = "w2_" + key([cfg["config_hash"], templates["artifacts"],
                          templates["protocol_hash"]])[:16]
    return run_id, Path(cfg["experiment_dir"]) / run_id


def _components(cfg):
    model_cfg = cfg["model"]
    final_dir = Path(cfg["w4_release_dir"])
    final = verified_manifest(final_dir, "manifest.json")
    w4 = _read(final_dir / "release_manifest.json")
    if w4.get("release") != "v0.2" or w4.get("default_model") != "logistic_regression":
        raise ValueError("W4 release does not publish logistic_regression as the default model")
    templates_dir = Path(model_cfg["artifact_dir"])
    templates = verified_manifest(templates_dir, "templates.json")
    run_id, run_dir = _w2_run(model_cfg, templates)
    training = verified_manifest(run_dir, "training.json")
    if training.get("run_id") != run_id:
        raise ValueError("W2 model run identity does not match frozen artifacts")
    if training.get("config_hash") != model_cfg["config_hash"]:
        raise ValueError("W2 model configuration changed")
    if training.get("template_manifest_hash") != key(templates["artifacts"]):
        raise ValueError("W2 model and Drain3 snapshot do not match")
    threshold = w4["thresholds"]["logistic_regression"]
    if float(training["thresholds"]["logistic_regression"]) != float(threshold):
        raise ValueError("W4 threshold does not match the registered W2 threshold")
    files = {
        "drain3_state": templates_dir / "drain3_state.bin",
        "template_vocab": templates_dir / "template_vocab.json",
        "tfidf": run_dir / "tfidf.joblib",
        "logistic_regression": run_dir / "logistic_regression.joblib",
        "w2_training": run_dir / "training.json",
        "w2_templates": templates_dir / "templates.json",
        "w4_release": final_dir / "release_manifest.json",
        "w4_manifest": final_dir / "manifest.json",
    }
    return w4, final, templates, training, files, float(threshold)


def publish(cfg):
    w4, final, templates, training, files, threshold = _components(cfg)
    directory = Path(cfg["release_dir"])
    directory.mkdir(parents=True, exist_ok=True)
    value = {
        "schema_version": 1,
        "release_id": SERVICE_RELEASE,
        "model_id": "logistic_regression",
        "model_family": "tfidf_lr",
        "threshold": threshold,
        "anomaly_score_semantics": "larger_is_more_anomalous_uncalibrated",
        "service_config_hash": cfg["config_hash"],
        "processing_hash": cfg["processing_hash"],
        "w4_release": w4["release"],
        "w4_manifest_hash": digest(files["w4_manifest"]),
        "w2_run_id": training["run_id"],
        "protocol_hash": training["protocol_hash"],
        "template_manifest_hash": training["template_manifest_hash"],
        "selected_similarity": templates["selected_similarity"],
        "component_hashes": {name: digest(path) for name, path in files.items()},
    }
    target = directory / "service_release.json"
    if target.exists():
        existing = _read(target)
        if existing != value:
            raise ValueError("A different service release already exists")
    else:
        save(target, value)
    registry = {
        "schema_version": 1,
        "release_id": SERVICE_RELEASE,
        "artifacts": {"service_release.json": digest(target)},
    }
    save(directory / "registry.json", registry)
    return value


def verify(cfg):
    directory = Path(cfg["release_dir"])
    verified_manifest(directory, "registry.json")
    release = _read(directory / "service_release.json")
    if release.get("service_config_hash") != cfg["config_hash"]:
        raise ValueError("Service configuration changed after publication")
    w4, _final, templates, training, files, threshold = _components(cfg)
    actual = {name: digest(path) for name, path in files.items()}
    if actual != release.get("component_hashes"):
        raise ValueError("A published model component changed")
    if release.get("threshold") != threshold or release.get("release_id") != SERVICE_RELEASE:
        raise ValueError("Published threshold or release identity changed")
    if w4["default_model"] != release["model_id"]:
        raise ValueError("Published default model changed")
    return release


class FrozenRelease:
    def __init__(self, cfg):
        self.cfg = cfg
        self.manifest = verify(cfg)
        model_cfg = cfg["model"]
        templates_dir = Path(model_cfg["artifact_dir"])
        templates = verified_manifest(templates_dir, "templates.json")
        _run_id, run_dir = _w2_run(model_cfg, templates)
        vectorizer_path = (run_dir / "tfidf.joblib").resolve()
        model_path = (run_dir / "logistic_regression.joblib").resolve()
        if vectorizer_path.parent != run_dir.resolve() or model_path.parent != run_dir.resolve():
            raise ValueError("Model files escaped the registered run directory")
        self.vectorizer = joblib.load(vectorizer_path)
        self.model = joblib.load(model_path)
        self.threshold = float(self.manifest["threshold"])
        self.snapshot = templates_dir / "drain3_state.bin"
        self.snapshot_hash = digest(self.snapshot)
        self.miner = TemplateMiner(
            FilePersistence(str(self.snapshot)),
            miner_config(model_cfg, templates["selected_similarity"]),
        )

    def template(self, row):
        cluster = self.miner.match(content(row), full_search_strategy="always")
        return 0 if cluster is None else int(cluster.cluster_id)

    def score(self, sequences):
        documents = [" ".join(f"T{value}" for value in values) for values in sequences]
        matrix = self.vectorizer.transform(documents)
        scores = np.asarray(self.model.decision_function(matrix), dtype=np.float64)
        return scores, (scores >= self.threshold).astype(np.int8)

    def assert_unchanged(self):
        if digest(self.snapshot) != self.snapshot_hash:
            raise ValueError("Frozen Drain3 snapshot changed during inference")

    def public(self):
        return {key: self.manifest[key] for key in (
            "schema_version", "release_id", "model_id", "model_family", "threshold",
            "anomaly_score_semantics", "protocol_hash", "template_manifest_hash",
        )}
