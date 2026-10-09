import hashlib
import json
from pathlib import Path

import yaml


def digest(path, algorithm="sha256"):
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def key(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def config(path):
    path = Path(path).resolve()
    c = yaml.safe_load(path.read_text(encoding="utf-8"))
    root = path.parent.parent
    for name in ("raw_dir", "output_dir"):
        c[name] = str((root / c[name]).resolve())
    return c


def verified_manifest(directory, name):
    directory = Path(directory)
    m = json.loads((directory / name).read_text(encoding="utf-8"))
    for filename, expected in m["artifacts"].items():
        if digest(directory / filename) != expected:
            raise ValueError(f"Artifact changed: {filename}")
    return m
