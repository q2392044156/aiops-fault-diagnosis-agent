"""验证 trace/span 的写入、父子关系与空实现。"""

import json

from aiops_diag.platform.db import Database
from aiops_diag.platform.tracing import NullTrace, SpanRecord, Tracer


# test_tracer_records_parent_and_attributes 验证 span 落库与父子关系。
def test_tracer_records_parent_and_attributes(tmp_path):
    database = Database(tmp_path / "service.sqlite3")
    database.init()
    tracer = Tracer(database)
    trace = tracer.bind(tracer.new_trace(), "dia_trace_test")
    parent = SpanRecord("agent.node", "node", attributes={"node": "VALIDATED"})
    parent.finish(12.5)
    trace.record(parent)
    child = SpanRecord("tool.query_logs", "tool", parent_id=parent.span_id,
                       attributes={"tool": "query_logs"})
    child.finish(3.0, status="ok", reused=False)
    trace.record(child)

    rows = database.spans("dia_trace_test")
    assert len(rows) == 2
    assert rows[0]["name"] == "agent.node"
    assert rows[1]["parent_id"] == rows[0]["span_id"]
    assert json.loads(rows[1]["attributes_json"])["tool"] == "query_logs"
    assert rows[1]["duration_ms"] == 3.0


# test_null_trace_is_noop 验证未启用追踪时不会报错。
def test_null_trace_is_noop():
    trace = NullTrace()
    assert trace.new_span() is None
    trace.record(SpanRecord("x", "internal"))


# test_tracer_disabled_without_database_support 验证无 add_span 时自动降级。
def test_tracer_disabled_without_database_support():
    # Database 是不支持 span 写入的桩对象。
    class Database:
        pass

    tracer = Tracer(Database())
    assert tracer.enabled is False
    assert isinstance(tracer.bind("trace"), NullTrace)
