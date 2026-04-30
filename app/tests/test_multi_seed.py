"""Tests for multi-seed and multi-model benchmark functionality."""
import csv
from pathlib import Path
from unittest.mock import patch, MagicMock

from text2query.benchmark.llm_benchmark import run_llm_generation, execute_generated_queries
from text2query.benchmark.reporting import (
    _format_summary_multiseed, _format_per_query_multiseed, _compute_stats,
    archive_session, model_slug, generate_cross_model_report,
)


def _make_question_file(questions_dir: Path, qid: str, question: str):
    """Create a question .md file in the expected format."""
    content = f'# Business Question:\n  "{question}"\n'
    (questions_dir / f"{qid}.md").write_text(content)


def test_run_llm_generation_single_seed_no_subdirs(tmp_path):
    """When seeds=None, output goes directly to output_dir (backward compat)."""
    questions_dir = tmp_path / "questions"
    output_dir = tmp_path / "output"
    questions_dir.mkdir()
    _make_question_file(questions_dir, "01", "What are the customer names?")

    def mock_streaming(*args, **kwargs):
        yield {"type": "done", "sql": "SELECT name FROM customers;"}

    with patch("text2query.benchmark.llm_benchmark.get_sql_from_llm_streaming", side_effect=mock_streaming), \
         patch("text2query.benchmark.llm_benchmark.create_engine_for_database"), \
         patch("text2query.benchmark.llm_benchmark.get_database_schema_string", return_value="schema"):

        run_llm_generation(questions_dir, output_dir, "db://url", "test-model", seeds=None)

    assert (output_dir / "01.sql").exists()
    assert not list(output_dir.glob("seed_*"))  # No seed subdirs


def test_run_llm_generation_multi_seed_creates_subdirs(tmp_path):
    """When seeds=[1,2,3], output goes to seed_1/, seed_2/, seed_3/ subdirs."""
    questions_dir = tmp_path / "questions"
    output_dir = tmp_path / "output"
    questions_dir.mkdir()
    _make_question_file(questions_dir, "01", "What are the customer names?")

    captured_seeds = []

    def mock_streaming(*args, **kwargs):
        captured_seeds.append(kwargs.get("seed"))
        yield {"type": "done", "sql": f"SELECT name FROM customers; -- seed={kwargs.get('seed')}"}

    with patch("text2query.benchmark.llm_benchmark.get_sql_from_llm_streaming", side_effect=mock_streaming), \
         patch("text2query.benchmark.llm_benchmark.create_engine_for_database"), \
         patch("text2query.benchmark.llm_benchmark.get_database_schema_string", return_value="schema"):

        results = run_llm_generation(
            questions_dir, output_dir, "db://url", "test-model", seeds=[1, 2, 3],
        )

    # Should create seed subdirectories
    assert (output_dir / "seed_1" / "01.sql").exists()
    assert (output_dir / "seed_2" / "01.sql").exists()
    assert (output_dir / "seed_3" / "01.sql").exists()

    # Seeds should be passed to the LLM
    assert captured_seeds == [1, 2, 3]

    # Results should include seed info
    assert all("seed" in r for r in results)


def test_run_llm_generation_caching_per_seed(tmp_path):
    """Already-generated seed dirs should be skipped."""
    questions_dir = tmp_path / "questions"
    output_dir = tmp_path / "output"
    questions_dir.mkdir()
    _make_question_file(questions_dir, "01", "What are the customer names?")

    # Pre-create seed_1 output
    seed1_dir = output_dir / "seed_1"
    seed1_dir.mkdir(parents=True)
    (seed1_dir / "01.sql").write_text("SELECT 1;")

    call_count = 0

    def mock_streaming(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        yield {"type": "done", "sql": "SELECT name FROM customers;"}

    with patch("text2query.benchmark.llm_benchmark.get_sql_from_llm_streaming", side_effect=mock_streaming), \
         patch("text2query.benchmark.llm_benchmark.create_engine_for_database"), \
         patch("text2query.benchmark.llm_benchmark.get_database_schema_string", return_value="schema"):

        run_llm_generation(
            questions_dir, output_dir, "db://url", "test-model", seeds=[1, 2],
        )

    # seed_1 was already cached, only seed_2 should be generated
    assert call_count == 1
    assert (output_dir / "seed_2" / "01.sql").exists()


def test_format_summary_multiseed():
    """Summary format should include mean±std, CI columns, and per-query seeds-ok count."""
    aggregated = [
        {
            "query_id": 1,
            "result_f1": _compute_stats([0.85, 0.72, 0.88]),
            "ast_similarity": _compute_stats([0.75, 0.80, 0.78]),
            "per_seed": [
                {"status": "ok"}, {"status": "ok"}, {"status": "ok"},
            ],
        },
        {
            "query_id": 2,
            "result_f1": _compute_stats([0.0, 0.0, 0.0]),
            "ast_similarity": _compute_stats([0.10, 0.12, 0.08]),
            "per_seed": [
                {"status": "ok"}, {"status": "exec_error"}, {"status": "missing"},
            ],
        },
    ]

    output = _format_summary_multiseed(aggregated, num_seeds=3)

    assert "3 seeds" in output
    assert "±" in output
    assert "01" in output
    assert "02" in output
    assert "3/3" in output   # query 1: all ok
    assert "1/3" in output   # query 2: only one ok


def test_format_per_query_multiseed():
    """Per-query multi-seed format should show all seed results."""
    seed_results = [
        {"seed": 1, "status": "ok", "result_f1": 0.85, "ast_similarity": 0.75},
        {"seed": 2, "status": "ok", "result_f1": 0.72, "ast_similarity": 0.80},
    ]

    output = _format_per_query_multiseed(seed_results)

    assert "Seed" in output
    assert "Aggregated" in output
    assert "Mean" in output
    assert "0.8500" in output  # seed 1 f1
    assert "0.7200" in output  # seed 2 f1
    assert "2 / 2" in output   # seeds executed


def test_format_per_query_multiseed_partial_failure():
    """Seeds executed count should reflect actual ok seeds."""
    seed_results = [
        {"seed": 1, "status": "ok", "result_f1": 0.80, "ast_similarity": 0.70},
        {"seed": 2, "status": "exec_error", "result_f1": 0.0, "ast_similarity": 0.30},
        {"seed": 3, "status": "missing", "result_f1": None, "ast_similarity": None},
    ]

    output = _format_per_query_multiseed(seed_results)

    assert "1 / 3" in output


def test_archive_with_seed_subdirs(tmp_path):
    """Archive should handle seed subdirectories correctly."""
    queries = tmp_path / "queries"
    answers = tmp_path / "answers"
    report = tmp_path / "report"
    results_base = tmp_path / "results"

    # Create seed subdirectories
    for seed in [1, 2]:
        seed_q = queries / f"seed_{seed}"
        seed_a = answers / f"seed_{seed}"
        seed_q.mkdir(parents=True)
        seed_a.mkdir(parents=True)
        (seed_q / "01.sql").write_text(f"SELECT {seed}")
        (seed_a / "01.csv").write_text(f"id\n{seed}\n")

    report.mkdir(parents=True)
    (report / "summary.md").write_text("# Summary")

    session_dir = archive_session(queries, answers, report, results_base)

    assert session_dir.exists()
    assert (session_dir / "queries" / "seed_1" / "01.sql").exists()
    assert (session_dir / "queries" / "seed_2" / "01.sql").exists()
    assert (session_dir / "answers" / "seed_1" / "01.csv").exists()
    assert (session_dir / "answers" / "seed_2" / "01.csv").exists()
    assert (session_dir / "report" / "summary.md").exists()
    assert not queries.exists()
    assert not answers.exists()


# --- Multi-model tests ---

def test_model_slug_basic():
    assert model_slug("qwen2.5-coder:7b") == "qwen2.5-coder_7b"
    assert model_slug("llama3.2:3b") == "llama3.2_3b"


def test_model_slug_with_slashes():
    assert model_slug("org/model:tag") == "org_model_tag"


def test_cross_model_csv_export(tmp_path):
    """CSV export should contain one row per (model, query, seed) combination."""
    ref_queries = tmp_path / "ref_queries"
    ref_answers = tmp_path / "ref_answers"
    gen_queries = tmp_path / "gen_queries"
    gen_answers = tmp_path / "gen_answers"
    report_dir = tmp_path / "report"

    ref_queries.mkdir()
    ref_answers.mkdir()

    # Create reference data
    (ref_queries / "01.sql").write_text("SELECT name FROM customers;")
    (ref_answers / "01.csv").write_text("name\nAlice\nBob\n")

    # Create model outputs (2 models, single seed)
    for model_name in ["model_a", "model_b"]:
        mq = gen_queries / model_name
        ma = gen_answers / model_name
        mq.mkdir(parents=True)
        ma.mkdir(parents=True)
        (mq / "01.sql").write_text("SELECT name FROM customers;")
        (ma / "01.csv").write_text("name\nAlice\nBob\n")

    generate_cross_model_report(
        models=["model_a", "model_b"],
        reference_queries_dir=ref_queries,
        reference_answers_dir=ref_answers,
        generated_queries_base=gen_queries,
        generated_answers_base=gen_answers,
        report_dir=report_dir,
        seeds=None,
    )

    csv_path = report_dir / "results.csv"
    assert csv_path.exists()

    with open(csv_path) as f:
        rows = list(csv.DictReader(f))

    # 2 models × 1 query × 1 seed = 2 rows
    assert len(rows) == 2
    assert rows[0]["model"] == "model_a"
    assert rows[1]["model"] == "model_b"
    assert all(r["query_id"] == "01" for r in rows)


def test_cross_model_comparison_report(tmp_path):
    """Comparison report should contain model names and per-query data."""
    ref_queries = tmp_path / "ref_queries"
    ref_answers = tmp_path / "ref_answers"
    gen_queries = tmp_path / "gen_queries"
    gen_answers = tmp_path / "gen_answers"
    report_dir = tmp_path / "report"

    ref_queries.mkdir()
    ref_answers.mkdir()

    (ref_queries / "01.sql").write_text("SELECT 1;")
    (ref_answers / "01.csv").write_text("col\n1\n")

    for model_name in ["alpha", "beta"]:
        mq = gen_queries / model_name
        ma = gen_answers / model_name
        mq.mkdir(parents=True)
        ma.mkdir(parents=True)
        (mq / "01.sql").write_text("SELECT 1;")
        (ma / "01.csv").write_text("col\n1\n")

    generate_cross_model_report(
        models=["alpha", "beta"],
        reference_queries_dir=ref_queries,
        reference_answers_dir=ref_answers,
        generated_queries_base=gen_queries,
        generated_answers_base=gen_answers,
        report_dir=report_dir,
    )

    comparison = (report_dir / "comparison.md").read_text()
    assert "alpha" in comparison
    assert "beta" in comparison
    assert "Cross-Model" in comparison
    assert "2 models" in comparison


def test_archive_with_model_subdirs(tmp_path):
    """Archive should handle model+seed subdirectories."""
    queries = tmp_path / "queries"
    answers = tmp_path / "answers"
    report = tmp_path / "report"
    results_base = tmp_path / "results"

    for model in ["model_a", "model_b"]:
        mq = queries / model
        ma = answers / model
        mq.mkdir(parents=True)
        ma.mkdir(parents=True)
        (mq / "01.sql").write_text("SELECT 1")
        (ma / "01.csv").write_text("id\n1\n")

    report.mkdir(parents=True)
    (report / "comparison.md").write_text("# Comparison")

    session_dir = archive_session(queries, answers, report, results_base)

    assert session_dir.exists()
    assert (session_dir / "queries" / "model_a" / "01.sql").exists()
    assert (session_dir / "queries" / "model_b" / "01.sql").exists()
    assert (session_dir / "report" / "comparison.md").exists()

