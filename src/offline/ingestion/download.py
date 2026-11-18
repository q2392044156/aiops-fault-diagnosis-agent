"""
下载模块

用于从远程 URL 下载 HDFS 日志归档文件，并进行验证和解压。
"""
import json
import shutil
import time
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from aiops_diag.common import digest, save


# 主要用于从远程 URL 下载归档文件（如 ZIP），并确保下载完整性。
# 输入：
#   url: 远程 URL，指向归档文件。
#   target: 本地目标路径，用于保存下载的归档文件。
#   size: 期望的归档文件大小，用于验证下载完整性。
#   md5: 期望的归档文件 MD5 哈希值，用于验证下载完整性。
#   attempts: 最大尝试次数，默认 4 次。
# 输出：
#   无返回值，下载结果直接写入 target 路径。
def fetch(url, target, size, md5, attempts=4):
    # 前置检查
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.stat().st_size == size and digest(target, "md5") == md5:
            return
        raise ValueError("Existing archive failed verification; preserve and inspect it")
    partial = target.with_suffix(target.suffix + ".partial")
    # 下载尝试循环
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

#用于从下载好的 ZIP 文件中提取指定的白名单文件到目标目录
#该函数确保解压过程安全，防止路径遍历攻击，并将提取的文件保存为指定的名称。
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

# 核心职责是并发保护 + 流程编排——本身不执行实际下载逻辑，而是做前置防护、调用内部实现、收尾清理
def download(c):
    raw = Path(c["raw_dir"])
    raw.mkdir(parents=True, exist_ok=True)
    lock = raw / "download.lock"
    try:
        handle = lock.open("x")
    except FileExistsError:
        raise ValueError(
            "Download already running; inspect download.lock if a previous process was killed") from None
    try:
        with handle:
            return _download(c, raw)
    finally:
        lock.unlink()

# 串联了磁盘检查 → 远程元数据校验 → 下载 → 解压 → 存证五个阶段，是整个下载管道的中枢
def _download(c, raw):
    # 磁盘检查， 确保有足够的空间来存储下载的文件
    if shutil.disk_usage(raw).free < c["min_free_gb"] * 1024 ** 3:
        raise ValueError("Less than required free disk space")
    # 远程元数据校验， 确保下载的文件与配置中的元数据一致
    with urllib.request.urlopen(f'https://zenodo.org/api/records/{c["record"]}', timeout=90) as r:
        metadata = json.load(r)
    # 查找指定的文件条目，并验证其大小和校验和是否与配置一致
    entry = next(f for f in metadata["files"] if f["key"] == "HDFS_v1.zip")
    if entry["size"] != c["size"] or entry["checksum"] != "md5:" + c["md5"]:
        raise ValueError("Pinned metadata differs from Zenodo")
    # 下载文件
    archive = raw / "HDFS_v1.zip"
    fetch(c["url"], archive, c["size"], c["md5"])
    extract(archive, raw)
    # 存证，记录下载的文件信息和校验结果
    save(raw / "download.json", {"schema_version": 1, "record": c["record"], "url": c["url"],
         "verified_at": datetime.now(UTC).isoformat(),
         "size": c["size"], "md5": c["md5"], "artifacts": {
             p.name: digest(p) for p in (archive, raw / "HDFS.log", raw / "anomaly_label.csv")}})
    # 返回结果，指示下载和验证成功，并提供存证文件的路径
    return {"status": "verified", "manifest": str(raw / "download.json")}
