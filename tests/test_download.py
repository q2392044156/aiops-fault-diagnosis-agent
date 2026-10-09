import hashlib
import io
import zipfile

import pytest

from aiops_diag.data.download import fetch, extract, download


class Response(io.BytesIO):
    def __init__(self, data, status, headers):
        super().__init__(data)
        self.status, self.headers = status, headers


@pytest.mark.parametrize("resume,ignore", [(False, False), (True, False), (True, True)])
def test_download(tmp_path, monkeypatch, resume, ignore):
    content = b"abcdefghij"
    target = tmp_path / "a.zip"
    if resume:
        target.with_suffix(".zip.partial").write_bytes(content[:3])
    def open_url(req, timeout):
        offset = int(req.headers.get("Range", "bytes=0-").split("=")[1].split("-")[0])
        if ignore:
            return Response(content, 200, {})
        return Response(content[offset:], 206, {"Content-Range": f"bytes {offset}-9/10"})
    monkeypatch.setattr("urllib.request.urlopen", open_url)
    fetch("https://example.com", target, 10, hashlib.md5(content).hexdigest())
    assert target.read_bytes() == content


def test_wrong_hash_and_range(tmp_path, monkeypatch):
    target = tmp_path / "a.zip"
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response(b"abc", 200, {}))
    with pytest.raises(ValueError, match="MD5"):
        fetch("https://example.com", target, 3, "wrong")
    assert not target.exists()
    target.with_suffix(".zip.partial").write_bytes(b"a")
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response(b"bc", 206, {"Content-Range": "bytes 0-2/3"}))
    with pytest.raises(ValueError, match="Content-Range"):
        fetch("https://example.com", target, 3, "wrong")


def test_zip(tmp_path):
    archive = tmp_path / "a.zip"
    archive.write_bytes(b"not a zip")
    with pytest.raises(zipfile.BadZipFile):
        extract(archive, tmp_path)
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../escape", "bad")
    with pytest.raises(ValueError, match="Unsafe"):
        extract(archive, tmp_path)


def test_extract_allowlist(tmp_path):
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("HDFS.log", "raw")
        z.writestr("preprocessed/anomaly_label.csv", "labels")
        z.writestr("preprocessed/Event_traces.csv", "do not use")
    extract(archive, tmp_path)
    assert (tmp_path / "HDFS.log").read_text() == "raw"
    assert (tmp_path / "anomaly_label.csv").read_text() == "labels"
    assert not (tmp_path / "preprocessed").exists()


def test_retry_and_existing(tmp_path, monkeypatch):
    target = tmp_path / "a.zip"
    calls = []
    def open_url(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("temporary failure")
        return Response(b"abc", 200, {})
    monkeypatch.setattr("urllib.request.urlopen", open_url)
    monkeypatch.setattr("time.sleep", lambda n: None)
    fetch("https://example.com", target, 3, hashlib.md5(b"abc").hexdigest())
    fetch("https://example.com", target, 3, hashlib.md5(b"abc").hexdigest())
    assert len(calls) == 2


def test_download_lock(tmp_path):
    (tmp_path / "download.lock").write_text("active")
    with pytest.raises(ValueError, match="already running"):
        download({"raw_dir": str(tmp_path)})
    assert (tmp_path / "download.lock").exists()
