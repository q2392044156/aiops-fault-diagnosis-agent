import json
import os
import shutil
import uuid
from pathlib import Path

import joblib
import numpy as np
from drain3.file_persistence import FilePersistence
from drain3.template_miner import TemplateMiner

from aiops_diag.data.common import digest, key, save, verified_manifest
from aiops_diag.modeling.templates import content, miner_config


MODEL_RELEASE = "v0.2_lr"
DEPLOYMENT_RELEASE = "v0.4"


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


def _bundle_names(files):
    suffixes = {
        "drain3_state": ".bin", "template_vocab": ".json", "tfidf": ".joblib",
        "logistic_regression": ".joblib", "w2_training": ".json",
        "w2_templates": ".json", "w4_release": ".json", "w4_manifest": ".json",
    }
    return {name: f"components/{name}{suffixes[name]}" for name in files}


def publish(cfg):
    """Build an atomic, self-contained and path-portable CPU service bundle."""
    w4, _final, templates, training, files, threshold = _components(cfg)
    directory = Path(cfg["release_dir"])
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = directory.parent / f".{directory.name}.{uuid.uuid4().hex}.partial"
    staging.mkdir(parents=True)
    try:
        names = _bundle_names(files)
        for name, source in files.items():
            target = staging / names[name]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        component_hashes = {name: digest(staging / relative)
                            for name, relative in names.items()}
        parser = cfg.get("model", {}).get("parser", {"depth": 4, "max_children": 100})
        rag_release = None
        if cfg.get("rag"):
            from aiops_diag.rag.release import verify as verify_rag
            rag_release = verify_rag(cfg["rag"])
        value = {
            "schema_version": 3,
            "deployment_release": DEPLOYMENT_RELEASE,
            "release_id": MODEL_RELEASE,
            "model_id": "logistic_regression",
            "model_family": "tfidf_lr",
            "threshold": threshold,
            "anomaly_score_semantics": "larger_is_more_anomalous_uncalibrated",
            "service_config_hash": cfg["config_hash"],
            "processing_hash": cfg["processing_hash"],
            "w4_release": w4["release"],
            "w2_run_id": training["run_id"],
            "protocol_hash": training["protocol_hash"],
            "template_manifest_hash": training["template_manifest_hash"],
            "selected_similarity": templates["selected_similarity"],
            "parser": {
                "depth": int(parser["depth"]),
                "max_children": int(parser["max_children"]),
            },
            "components": names,
            "component_hashes": component_hashes,
            "rag_release": ({"rag_version": rag_release["rag_version"],
                             "kb_release_id": rag_release["kb_release_id"],
                             "release_hash": key(rag_release)} if rag_release else None),
        }
        save(staging / "service_release.json", value)
        registry = {
            "schema_version": 3,
            "deployment_release": DEPLOYMENT_RELEASE,
            "release_id": MODEL_RELEASE,
            "artifacts": {"service_release.json": digest(staging / "service_release.json"),
                          **{relative: component_hashes[name]
                             for name, relative in names.items()}},
        }
        save(staging / "registry.json", registry)
        verified_manifest(staging, "registry.json")
        if directory.exists():
            previous = directory.parent / f".{directory.name}.previous"
            if previous.exists():
                shutil.rmtree(previous)
            os.replace(directory, previous)
            try:
                os.replace(staging, directory)
            except Exception:
                os.replace(previous, directory)
                raise
            shutil.rmtree(previous)
        else:
            os.replace(staging, directory)
        return value
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def verify(cfg, verify_rag=True):
    """Verify only the portable bundle; source experiment directories are not required."""
    directory = Path(cfg["release_dir"]).resolve()
    registry = verified_manifest(directory, "registry.json")
    release = _read(directory / "service_release.json")
    if release.get("schema_version") not in (2, 3):
        raise ValueError("Unsupported service release schema")
    if release.get("deployment_release") != DEPLOYMENT_RELEASE:
        raise ValueError("Unexpected deployment release")
    if release.get("release_id") != MODEL_RELEASE:
        raise ValueError("Published model release changed")
    if release.get("processing_hash") != cfg["processing_hash"]:
        raise ValueError("Processing configuration changed after publication")
    if verify_rag and release.get("schema_version") == 3 and cfg.get("rag"):
        from aiops_diag.rag.release import verify as verify_rag
        rag_release = verify_rag(cfg["rag"])
        expected_rag = release.get("rag_release") or {}
        if expected_rag.get("release_hash") != key(rag_release):
            raise ValueError("Published RAG release changed")
    expected = release.get("component_hashes", {})
    components = release.get("components", {})
    if set(expected) != set(components):
        raise ValueError("Published component registry is incomplete")
    for name, relative in components.items():
        path = (directory / relative).resolve()
        if directory not in path.parents:
            raise ValueError("Published component escaped the release directory")
        if digest(path) != expected[name]:
            raise ValueError(f"Published component changed: {name}")
        if registry["artifacts"].get(relative) != expected[name]:
            raise ValueError(f"Registry hash changed: {name}")
    return release


class ReleaseMetadata:
    """Hash-verified release metadata for API processes; does not deserialize models."""

    def __init__(self, cfg, verify_rag=True):
        self.manifest = verify(cfg, verify_rag=verify_rag)

    def public(self):
        return {name: self.manifest[name] for name in (
            "schema_version", "deployment_release", "release_id", "model_id",
            "model_family", "threshold", "anomaly_score_semantics", "protocol_hash",
            "template_manifest_hash",
        )}


class FrozenRelease(ReleaseMetadata):
    def __init__(self, cfg):
        super().__init__(cfg, verify_rag=False)
        directory = Path(cfg["release_dir"]).resolve()

        def component(name):
            path = (directory / self.manifest["components"][name]).resolve()
            if directory not in path.parents:
                raise ValueError("Model file escaped the registered release directory")
            return path

        self.vectorizer = joblib.load(component("tfidf"))
        self.model = joblib.load(component("logistic_regression"))
        self.threshold = float(self.manifest["threshold"])
        self.snapshot = component("drain3_state")
        self.snapshot_hash = digest(self.snapshot)
        parser_cfg = {"parser": self.manifest["parser"]}
        self.miner = TemplateMiner(
            FilePersistence(str(self.snapshot)),
            miner_config(parser_cfg, self.manifest["selected_similarity"]),
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
