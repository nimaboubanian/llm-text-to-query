"""Locals-first model ordering and the HTTP 429 mid-run abort."""
from backend.benchmark.benchmarking import _sort_locals_first


def test_locals_sort_before_cloud_models():
    models = ["qwen3-coder:480b-cloud", "qwen2.5-coder:7b"]
    assert _sort_locals_first(models) == ["qwen2.5-coder:7b", "qwen3-coder:480b-cloud"]


def test_sort_is_stable_within_each_group():
    """User order is meaningful (it decides which local runs first) — only the
    local/cloud split may reorder anything."""
    models = ["z-cloud", "sqlcoder:7b", "a-cloud", "qwen2.5-coder:7b", "b-cloud"]
    assert _sort_locals_first(models) == [
        "sqlcoder:7b", "qwen2.5-coder:7b", "z-cloud", "a-cloud", "b-cloud",
    ]


def test_sort_leaves_all_local_and_all_cloud_lists_untouched():
    locals_only = ["b:7b", "a:7b"]
    cloud_only = ["b-cloud", "a-cloud"]
    assert _sort_locals_first(locals_only) == locals_only
    assert _sort_locals_first(cloud_only) == cloud_only
    assert _sort_locals_first([]) == []
