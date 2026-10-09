import json
import shutil
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .common import digest, save


def fetch(url, target, size, md5, attempts=4):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.stat().st_size == size and digest(target, "md5") == md5:
            return
        raise ValueError("Existing archive failed verification; preserve and inspect it")
    partial = target.with_suffix(target.suffix + ".partial")
    for attempt in range(attempts):
        try:
            offset = partial.stat().st_size if partial.exists() else 0
            if offset > size:
                raise ValueError("Partial file exceeds expected size")
            if offset < size:
                headers = {"Accept-Encoding": "identity"}
                if offset:
                    headers["Range"] = f"bytes={offset}-"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=90) as response:
                    status = response.status
                    if status == 206:
                        expected = f"bytes {offset}-{size - 1}/{size}"
                        if response.headers.get("Content-Range") != expected:
                            raise ValueError("Unexpected Content-Range")
                        mode = "ab"
                    elif status == 200:
                        mode = "wb"
                    else:
                        raise ValueError(f"Unexpected status {status}")
                    with partial.open(mode) as out:
                        received = offset if mode == "ab" else 0
                        checkpoint = received
                        while chunk := response.read(256 * 1024):
                            out.write(chunk)
                            received += len(chunk)
                            if received > size:
                                raise ValueError("Response exceeds pinned size")
                            if received - checkpoint >= 10 * 1024 * 1024:
                                print(f"Downloaded {received:,}/{size:,} bytes", flush=True)
                                checkpoint = received
            if partial.stat().st_size != size or digest(partial, "md5") != md5:
                raise ValueError("Archive size or MD5 mismatch")
            partial.replace(target)
            return
        except (OSError, ValueError) as exc:
            if isinstance(exc, ValueError) or attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)


def extract(archive, raw):
    raw = Path(raw)
    allowed = {"HDFS.log": "HDFS.log", "preprocessed/anomaly_label.csv": "anomaly_label.csv"}
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP member")
        for name in names:
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name:
                raise ValueError("Unsafe ZIP path")
        for member, filename in allowed.items():
            target = raw / filename
            tmp = target.with_suffix(target.suffix + ".partial")
            with z.open(member) as src, tmp.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            tmp.replace(target)


def download(c):
    raw = Path(c["raw_dir"])
    raw.mkdir(parents=True, exist_ok=True)
    lock = raw / "download.lock"
    try:
        handle = lock.open("x")
    except FileExistsError:
        raise ValueError("Download already running; inspect download.lock if a previous process was killed")
    try:
        with handle:
            return _download(c, raw)
    finally:
        lock.unlink()


def _download(c, raw):
    if shutil.disk_usage(raw).free < c["min_free_gb"] * 1024 ** 3:
        raise ValueError("Less than required free disk space")
    with urllib.request.urlopen(f'https://zenodo.org/api/records/{c["record"]}', timeout=90) as r:
        metadata = json.load(r)
    entry = next(f for f in metadata["files"] if f["key"] == "HDFS_v1.zip")
    if entry["size"] != c["size"] or entry["checksum"] != "md5:" + c["md5"]:
        raise ValueError("Pinned metadata differs from Zenodo")
    archive = raw / "HDFS_v1.zip"
    fetch(c["url"], archive, c["size"], c["md5"])
    extract(archive, raw)
    save(raw / "download.json", {"schema_version": 1, "record": c["record"], "url": c["url"],
         "verified_at": datetime.now(timezone.utc).isoformat(),
         "size": c["size"], "md5": c["md5"], "artifacts": {
             p.name: digest(p) for p in (archive, raw / "HDFS.log", raw / "anomaly_label.csv")}})
    return {"status": "verified", "manifest": str(raw / "download.json")}
