"""
这是一个 HDFS 日志单行解析器

把原始的 HDFS 日志行（字节流）转换成结构化的字典记录，
并提供归一化（模板化）能力用于后续的异常检测/聚类分析。
"""
import hashlib
import re
from datetime import datetime
from functools import lru_cache

# 定义正则表达式模式，用于匹配日志行中的不同部分
BLOCK = re.compile(r"\bblk_-?\d+\b")
# 变量说明：`HEADER` 保存本模块或数据模型使用的稳定值。
HEADER = re.compile(r"^(\d{6}) (\d{6}) (\d+) ([A-Z]+) ([^: ]+):\s?(.*)$")
# 变量说明：`IP` 保存本模块或数据模型使用的稳定值。
IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")
# 变量说明：`NUMBER` 保存本模块或数据模型使用的稳定值。
NUMBER = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?")


# 缓存时间戳解析，避免重复计算
@lru_cache(maxsize=200000)
def timestamp(date, clock):
    return datetime.strptime(date + clock, "%y%m%d%H%M%S").isoformat()

# 解析单行日志，返回结构化字典记录
def parse(raw, number, offset, source_hash):
    text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
    blocks = sorted(set(BLOCK.findall(text)))
    row = dict(log_id=f"{source_hash}:{number}", raw_line_no=number, byte_offset=offset,
               byte_length=len(raw), raw_hash=hashlib.sha256(raw).hexdigest(),
               timestamp_original=None, timestamp_local=None, timestamp_utc=None,
               timezone_assumption="unknown", pid=None, level=None, component=None,
               message=None, session_ids=blocks, parse_status="ok")
    try:
        raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        row["parse_status"] = "decode_error"
        return row
    m = HEADER.fullmatch(text)
    if not m:
        row["parse_status"] = "format_error"
        return row
    date, clock, pid, level, component, message = m.groups()
    row.update(timestamp_original=date + " " + clock, pid=pid, level=level,
               component=component, message=message)
    try:
        row["timestamp_local"] = timestamp(date, clock)
    except ValueError:
        row["parse_status"] = "time_error"
    return row

# 归一化日志行，替换敏感信息和可变部分为占位符
def normalized(row):
    message = BLOCK.sub("<BLOCK>", row["message"] or "")
    message = IP.sub("<IP>", message)
    return (row["level"] or "") + "|" + (row["component"] or "") + "|" + NUMBER.sub("<NUM>", message)
