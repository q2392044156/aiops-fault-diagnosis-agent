"""记录诊断链路的 trace/span，写入 SQLite 供 API 与 UI 回放。"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime


# now 返回带时区的 ISO 时间戳。
def now():
    return datetime.now(UTC).isoformat()


# SpanRecord 是一次已完成调用的最小记录。
class SpanRecord:
    # __init__ 保存 span 的标识、时间与属性。
    def __init__(self, name, kind, parent_id=None, attributes=None, span_id=None,
                 started_at=None):
        self.span_id = span_id or uuid.uuid4().hex[:16]
        self.parent_id = parent_id
        self.name = name
        self.kind = kind
        self.started_at = started_at or now()
        self.duration_ms = 0.0
        self.status = "ok"
        self.attributes = dict(attributes or {})

    # finish 记录耗时与状态，返回自身便于链式调用。
    def finish(self, duration_ms, status="ok", **attributes):
        self.duration_ms = round(float(duration_ms), 3)
        self.status = status
        self.attributes.update(attributes)
        return self


# NullTrace 是未启用追踪时的空实现，保证调用方无需分支。
class NullTrace:
    # trace_id 为空，表示未启用追踪。
    trace_id = None

    # new_span 返回一个占位 ID。
    def new_span(self):
        return None

    # record 忽略任何记录请求。
    def record(self, record):
        return None


# Trace 绑定一个 trace_id 与受试对象，把 span 写入数据库。
class Trace:
    # __init__ 保存数据库、trace_id 与受试对象。
    def __init__(self, database, trace_id, subject_id=None):
        self.database = database
        self.trace_id = trace_id
        self.subject_id = subject_id

    # new_span 生成新的 span 标识。
    def new_span(self):
        return uuid.uuid4().hex[:16]

    # record 写入一条已完成 span，失败时静默降级不影响主流程。
    def record(self, record):
        try:
            self.database.add_span(self.trace_id, self.subject_id, record)
        except Exception:
            return None


# Tracer 负责创建 trace、绑定受试对象并判断是否启用。
class Tracer:
    # __init__ 检查数据库是否支持 span 写入。
    def __init__(self, database):
        self.database = database
        self.enabled = callable(getattr(database, "add_span", None))

    # new_trace 生成新的 trace 标识。
    def new_trace(self):
        return uuid.uuid4().hex

    # bind 返回绑定到某个 trace 与诊断的 Trace 对象。
    def bind(self, trace_id, subject_id=None):
        if not self.enabled or not trace_id:
            return NullTrace()
        return Trace(self.database, trace_id, subject_id)


# elapsed_ms 计算两个 monotonic 时间点之间的毫秒数。
def elapsed_ms(started):
    return (time.perf_counter() - started) * 1000
