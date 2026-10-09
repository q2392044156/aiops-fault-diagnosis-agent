import hashlib
import re
from datetime import datetime
from functools import lru_cache

BLOCK = re.compile(r"\bblk_-?\d+\b")
HEADER = re.compile(r"^(\d{6}) (\d{6}) (\d+) ([A-Z]+) ([^: ]+):\s?(.*)$")
IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")
NUMBER = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?")


@lru_cache(maxsize=200000)
def timestamp(date, clock):
    return datetime.strptime(date + clock, "%y%m%d%H%M%S").isoformat()


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


def normalized(row):
    message = BLOCK.sub("<BLOCK>", row["message"] or "")
    message = IP.sub("<IP>", message)
    return (row["level"] or "") + "|" + (row["component"] or "") + "|" + NUMBER.sub("<NUM>", message)
