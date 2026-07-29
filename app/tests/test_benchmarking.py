from pathlib import Path
from unittest.mock import patch

from text2query.benchmark.benchmarking import (
    BenchmarkPaths,
    _resolve_query_id_filter,
    _run_single_model_benchmark,
)


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


def test_benchmark_paths_defaults():
    paths = BenchmarkPaths.defaults()
    assert paths.schema_file == Path("benchmark/.tpch/schema.sql")
    assert paths.output_dir == Path("benchmark/queries")
    assert paths.results_base == Path("benchmark/results")


def test_run_single_model_benchmark_builds_per_model_subdirs():
    paths = BenchmarkPaths(
        schema_file=Path("s"), questions_dir=Path("q"), queries_dir=Path("qq"),
        answers_dir=Path("a"), output_dir=Path("out"), generated_answers_dir=Path("ga"),
        report_dir=Path("rep"), results_base=Path("res"),
    )
    captured = {}

    def fake_run_llm_generation(*, questions_dir, output_dir, db_url, model, seeds, query_ids):
        captured["run_llm_generation_output_dir"] = output_dir

    def fake_execute_generated_queries(*, queries_dir, answers_dir, db_url, seeds, query_ids):
        captured["execute_answers_dir"] = answers_dir

    def fake_generate_reports(**kwargs):
        captured["report_dir"] = kwargs["report_dir"]
        return [{"query_id": 1}]

    with patch("text2query.benchmark.benchmarking.run_llm_generation", fake_run_llm_generation), \
         patch("text2query.benchmark.benchmarking.execute_generated_queries", fake_execute_generated_queries), \
         patch("text2query.benchmark.benchmarking.generate_reports", fake_generate_reports):

        results = _run_single_model_benchmark(
            model="qwen2.5-coder:7b", paths=paths, db_url="db://url", seeds=[1],
        )

    assert captured["run_llm_generation_output_dir"] == Path("out/qwen2.5-coder_7b")
    assert captured["execute_answers_dir"] == Path("ga/qwen2.5-coder_7b")
    assert captured["report_dir"] == Path("rep/qwen2.5-coder_7b")
    assert results == [{"query_id": 1}]
