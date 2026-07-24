from text2query.benchmark.benchmarking import _resolve_query_id_filter


def test_no_filter_requested_returns_none():
    resolved, skipped = _resolve_query_id_filter(None, ["01", "02"])
    assert resolved is None
    assert skipped == []


def test_filter_keeps_only_available_ids():
    resolved, skipped = _resolve_query_id_filter(["01", "99"], ["01", "02"])
    assert resolved == ["01"]
    assert skipped == ["99"]


def test_filter_with_no_matches_returns_empty_list():
    resolved, skipped = _resolve_query_id_filter(["99"], ["01", "02"])
    assert resolved == []
    assert skipped == ["99"]
