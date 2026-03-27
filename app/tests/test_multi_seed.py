"""Tests for multi-seed benchmark functionality."""
from pathlib import Path
from unittest.mock import patch, MagicMock

from text2query.benchmark.llm_benchmark import run_llm_generation, execute_generated_queries
from text2query.benchmark.reporting import (
    _format_summary_multiseed, _format_per_query_multiseed, _compute_stats,
    archive_session,
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
    """Summary format should include mean±std and CI columns."""
    aggregated = [
        {
            "query_id": 1,
            "result_f1": _compute_stats([0.85, 0.72, 0.88]),
            "ast_similarity": _compute_stats([0.75, 0.80, 0.78]),
            "composite_score": _compute_stats([0.70, 0.65, 0.72]),
        },
        {
            "query_id": 2,
            "result_f1": _compute_stats([0.0, 0.0, 0.0]),
            "ast_similarity": _compute_stats([0.10, 0.12, 0.08]),
            "composite_score": _compute_stats([0.03, 0.04, 0.02]),
        },
    ]

    output = _format_summary_multiseed(aggregated, num_seeds=3)

    assert "3 seeds" in output
    assert "mean±std" in output.lower() or "±" in output
    assert "01" in output
    assert "02" in output


def test_format_per_query_multiseed():
    """Per-query multi-seed format should show all seed results."""
    seed_results = [
        {"seed": 1, "status": "ok", "result_f1": 0.85, "ast_similarity": 0.75,
         "bleu": 0.6, "token_jaccard": 0.7, "composite_score": 0.72},
        {"seed": 2, "status": "ok", "result_f1": 0.72, "ast_similarity": 0.80,
         "bleu": 0.55, "token_jaccard": 0.68, "composite_score": 0.65},
    ]

    output = _format_per_query_multiseed(seed_results)

    assert "Seed" in output
    assert "Aggregated" in output
    assert "Mean" in output
    assert "0.8500" in output  # seed 1 f1
    assert "0.7200" in output  # seed 2 f1


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
