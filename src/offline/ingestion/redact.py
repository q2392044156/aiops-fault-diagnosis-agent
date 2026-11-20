"""日志行的确定性脱敏与形状编号：生产链路与实验台共用同一套规则。"""

import hashlib
import re

BLOCK = re.compile(r"\bblk_-?\d+\b")
IP = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?::\d+)?(?![0-9])")
PATH = re.compile(r"(?<![A-Za-z0-9])(?:/[A-Za-z0-9._-]+){2,}")
HEX = re.compile(r"\b0x[0-9A-Fa-f]+\b")
NUM = re.compile(r"(?<![A-Za-z0-9])[-+]?\d+(?:\.\d+)?(?![A-Za-z0-9])")

RULES = (("BLOCK", BLOCK), ("IP", IP), ("PATH", PATH), ("HEX", HEX), ("NUM", NUM))

# shape_id 取形状哈希的低 31 位，0 保留给「没有形状」的行。
SHAPE_MODULUS = 2**31


def content(row):
    """把一条日志行归一为「级别 组件: 脱敏消息」，不含任何原始标识。"""
    message = row["message"] or ""
    message = BLOCK.sub("<:BLOCK:>", message)
    message = IP.sub("<:IP:>", message)
    message = PATH.sub("<:PATH:>", message)
    message = HEX.sub("<:HEX:>", message)
    message = NUM.sub("<:NUM:>", message)
    return f'{row["level"] or "UNKNOWN"} {row["component"] or "UNKNOWN"}: {message}'


def shape_id(text):
    """把脱敏文本映射为稳定的正整数形状编号，同一形状跨进程一致。"""
    if not text:
        return 0
    return int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:8], 16) % SHAPE_MODULUS or 1


def masking_spec():
    """返回参与发布的脱敏规则描述，供发布身份哈希使用。"""
    return [{"name": name, "pattern": pattern.pattern} for name, pattern in RULES]
