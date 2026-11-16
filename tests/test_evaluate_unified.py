"""模块说明：验证统一评测的案例口径与 cluster bootstrap。"""

from ops.scripts.evaluate_unified import _bootstrap


# 方法说明：构造一条案例级评测记录。
def _record(family, majority, first, all_events, any_event, events, hits):
    return {"family": family, "case_majority": majority, "case_first": first,
            "case_all_events": all_events, "case_any_event": any_event,
            "events": events, "event_hits": hits}


# 方法说明：验证 bootstrap 可复现、区间有序且覆盖全部指标。
def test_bootstrap_is_deterministic_and_bounded():
    records = [
        _record("heartbeat", 1, 1, 0, 1, 2, 1),
        _record("heartbeat", 0, 0, 0, 1, 2, 1),
        _record("volume", 1, 1, 1, 1, 1, 1),
        _record("volume", 1, 1, 1, 1, 1, 1),
    ]
    first = _bootstrap(records, 200, 7)
    second = _bootstrap(records, 200, 7)
    assert first == second
    assert set(first) == {"case_top1", "case_first", "case_all_events",
                           "case_any_event", "event_top1", "macro_event"}
    for interval in first.values():
        assert interval[0] <= interval[1]
        assert 0 <= interval[0] <= 1
        assert 0 <= interval[1] <= 1


# 方法说明：验证 100% 指标在非参数 bootstrap 下会退化为边界区间。
def test_bootstrap_marks_perfect_case_rate_as_boundary():
    records = [_record("volume", 1, 1, 1, 1, 1, 1) for _ in range(4)]
    intervals = _bootstrap(records, 100, 7)
    assert intervals["case_top1"] == [1.0, 1.0]
