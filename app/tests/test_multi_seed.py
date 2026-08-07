"""Tests for multi-seed and multi-model benchmark functionality."""
import csv
from pathlib import Path
from unittest.mock import patch

from backend.benchmark.runner import _run_single_generation, run_llm_generation
from backend.benchmark.reporting import (
    archive_session, generate_cross_model_report, generate_reports,
)
from backend.llm.ollama import GenerationResult


def _make_question_file(questions_dir: Path, qid: str, question: str):
    """Create a question .md file in the expected format."""
    content = f'# Business Question:\n  "{question}"\n'
    (questions_dir / f"{qid}.md").write_text(content)


def test_run_llm_generation_multi_seed_creates_subdirs(tmp_path, capsys):
    """When seeds=[1,2,3], output goes to seed_1/, seed_2/, seed_3/ subdirs."""
    questions_dir = tmp_path / "questions"
    output_dir = tmp_path / "output"
    questions_dir.mkdir()
    _make_question_file(questions_dir, "01", "What are the customer names?")

    captured_seeds = []

    def mock_generate(*args, **kwargs):
        captured_seeds.append(kwargs.get("seed"))
        return GenerationResult(sql=f"SELECT name FROM customers; -- seed={kwargs.get('seed')}")

    with patch("backend.llm.ollama.generate_sql", side_effect=mock_generate), \
         patch("backend.benchmark.runner.create_engine_for_database"), \
         patch("backend.llm.ollama.warmup", return_value=True), \
         patch("backend.benchmark.runner.render_schema", return_value="schema"):

        run_llm_generation(
            questions_dir, output_dir, "db://url", "test-model", seeds=[1, 2, 3],
        )

    # Should create seed subdirectories
    assert (output_dir / "seed_1" / "01.sql").exists()
    assert (output_dir / "seed_2" / "01.sql").exists()
    assert (output_dir / "seed_3" / "01.sql").exists()

    # Seeds should be passed to the LLM
    assert captured_seeds == [1, 2, 3]

    # The seed banner should announce each seed as it starts
    out = capsys.readouterr().out
    assert "  --- Seed 1 ---" in out
    assert "  --- Seed 2 ---" in out
    assert "  --- Seed 3 ---" in out


def test_run_llm_generation_single_seed_omits_seed_banner(tmp_path, capsys):
    questions_dir = tmp_path / "questions"
    questions_dir.mkdir()
    (questions_dir / "01.md").write_text('# Business Question:\n  "test?"\n')
    output_dir = tmp_path / "out"

    import backend.benchmark.runner as runner_mod
    from unittest.mock import patch
    from backend.llm.ollama import GenerationResult

    with patch.object(runner_mod, "create_engine_for_database", lambda url: None), \
         patch.object(runner_mod, "render_schema",
                      lambda engine, flags, metadata=None, include_tables=None: "schema"), \
         patch.object(runner_mod, "load_tpch_metadata", lambda: {}), \
         patch.object(runner_mod.ollama, "warmup", lambda model: True), \
         patch.object(
             runner_mod.ollama, "generate_sql_with_retry",
             lambda *a, **kw: GenerationResult(sql="SELECT 1", raw_response="SELECT 1", prompt="p", error=None, retried=False),
         ):
        run_llm_generation(questions_dir, output_dir, "postgresql://fake", "m1", seeds=[1])

    out = capsys.readouterr().out
    assert "--- Seed" not in out


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

    def mock_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return GenerationResult(sql="SELECT name FROM customers;")

    with patch("backend.llm.ollama.generate_sql", side_effect=mock_generate), \
         patch("backend.benchmark.runner.create_engine_for_database"), \
         patch("backend.llm.ollama.warmup", return_value=True), \
         patch("backend.benchmark.runner.render_schema", return_value="schema"):

        run_llm_generation(
            questions_dir, output_dir, "db://url", "test-model", seeds=[1, 2],
        )

    # seed_1 was already cached, only seed_2 should be generated
    assert call_count == 1
    assert (output_dir / "seed_2" / "01.sql").exists()


def test_run_single_generation_invokes_item_callbacks(tmp_path):
    questions_dir = tmp_path / "questions"
    output_dir = tmp_path / "output"
    questions_dir.mkdir()
    _make_question_file(questions_dir, "01", "What are the customer names?")

    starts = []
    outcomes = []

    with patch(
        "backend.llm.ollama.generate_sql",
        return_value=GenerationResult(sql="SELECT name FROM customers;"),
    ), patch("backend.benchmark.runner.create_engine_for_database"), \
       patch("backend.llm.ollama.warmup", return_value=True), \
       patch("backend.benchmark.runner.render_schema", return_value="schema"):

        _run_single_generation(
            questions_dir, output_dir, "db://url", "test-model",
            on_item_start=lambda i, total, label: starts.append((i, total, label)),
            on_item_done=lambda outcome: outcomes.append(outcome),
        )

    assert starts == [(1, 1, "Q01")]
    assert outcomes == [" ✓"]


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


def test_raw_file_written_on_api_error(tmp_path):
    """When Ollama returns an error chunk, a .raw file with ERROR: prefix is written."""
    questions_dir = tmp_path / "questions"
    output_dir = tmp_path / "output"
    questions_dir.mkdir()
    _make_question_file(questions_dir, "01", "What are the totals?")

    def mock_generate(*args, **kwargs):
        return GenerationResult(sql=None, error="Model 'bad-model' not found.")

    with patch("backend.llm.ollama.generate_sql", side_effect=mock_generate), \
         patch("backend.benchmark.runner.create_engine_for_database"), \
         patch("backend.llm.ollama.warmup", return_value=True), \
         patch("backend.benchmark.runner.render_schema", return_value="schema"):
        run_llm_generation(questions_dir, output_dir, "db://url", "bad-model", seeds=None)

    assert not (output_dir / "seed_1" / "01.sql").exists()
    raw = output_dir / "seed_1" / "01.raw"
    assert raw.exists()
    assert raw.read_text().startswith("ERROR:")
    assert "not found" in raw.read_text()


def test_raw_file_written_on_extraction_failure(tmp_path):
    """When model responds but no SQL can be extracted, .raw contains the raw output."""
    questions_dir = tmp_path / "questions"
    output_dir = tmp_path / "output"
    questions_dir.mkdir()
    _make_question_file(questions_dir, "01", "What are the totals?")

    raw_model_output = "I'm sorry, I cannot generate SQL for this question."

    def mock_generate(*args, **kwargs):
        return GenerationResult(sql=None, raw_response=raw_model_output)

    with patch("backend.llm.ollama.generate_sql", side_effect=mock_generate), \
         patch("backend.benchmark.runner.create_engine_for_database"), \
         patch("backend.llm.ollama.warmup", return_value=True), \
         patch("backend.benchmark.runner.render_schema", return_value="schema"):
        run_llm_generation(questions_dir, output_dir, "db://url", "test-model", seeds=None)

    assert not (output_dir / "seed_1" / "01.sql").exists()
    raw = output_dir / "seed_1" / "01.raw"
    assert raw.exists()
    assert raw.read_text() == raw_model_output


# --- Multi-model tests ---

def test_cross_model_csv_export(tmp_path):
    """CSV export should contain one row per (model, query, seed) combination."""
    ref_queries = tmp_path / "ref_queries"
    report_dir = tmp_path / "report"

    ref_queries.mkdir()

    # Create reference data
    (ref_queries / "01.sql").write_text("SELECT name FROM customers;")

    # Precomputed evaluation results (2 models, single seed, from generate_reports)
    precomputed = {
        model_name: [{
            "query_id": 1, "seed": 1, "status": "ok",
            "result_precision": 1.0, "result_recall": 1.0, "result_f1": 1.0,
            "ast_similarity": 1.0, "error_category": None,
            "nl_query": "What are the customer names?",
            "prompt": "prompt text",
            "generated_sql": "SELECT name FROM customers;",
            "real_sql": "SELECT name FROM customers;",
        }]
        for model_name in ["model_a", "model_b"]
    }

    generate_cross_model_report(
        models=["model_a", "model_b"],
        reference_queries_dir=ref_queries,
        report_dir=report_dir,
        precomputed=precomputed,
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
    # new columns present; real_sql/generated_sql populated from the SQL files
    assert "nl_query" in rows[0]
    assert "prompt" in rows[0]
    assert all(r["real_sql"] == "SELECT name FROM customers;" for r in rows)
    assert all(r["generated_sql"] == "SELECT name FROM customers;" for r in rows)


def test_results_csv_multiseed(tmp_path):
    """Multi-seed runs should emit one results.csv row per (query, seed)."""
    ref_queries = tmp_path / "ref_queries"
    ref_answers = tmp_path / "ref_answers"
    gen_queries = tmp_path / "gen_queries"
    gen_answers = tmp_path / "gen_answers"
    questions = tmp_path / "questions"
    report_dir = tmp_path / "report"
    for d in [ref_queries, ref_answers, gen_queries, gen_answers, questions]:
        d.mkdir()

    (ref_queries / "01.sql").write_text("SELECT name FROM customers;")
    (ref_answers / "01.csv").write_text("name\nAlice\n")
    _make_question_file(questions, "01", "What are the customer names?")

    for seed in [1, 2]:
        sq = gen_queries / f"seed_{seed}"
        sa = gen_answers / f"seed_{seed}"
        sq.mkdir(parents=True)
        sa.mkdir(parents=True)
        (sq / "01.sql").write_text("SELECT name FROM customers;")
        (sq / "01.prompt").write_text(f"prompt for seed {seed}")
        (sa / "01.csv").write_text("name\nAlice\n")

    generate_reports(
        generated_queries_dir=gen_queries,
        reference_queries_dir=ref_queries,
        generated_answers_dir=gen_answers,
        reference_answers_dir=ref_answers,
        report_dir=report_dir,
        seeds=[1, 2],
        model="m1",
        questions_dir=questions,
    )

    with open(report_dir / "results.csv") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 2
    assert {r["seed"] for r in rows} == {"1", "2"}
    assert all(r["nl_query"] == "What are the customer names?" for r in rows)
    assert all(r["real_sql"] == "SELECT name FROM customers;" for r in rows)
    by_seed = {r["seed"]: r for r in rows}
    assert by_seed["1"]["prompt"] == "prompt for seed 1"
    assert by_seed["2"]["prompt"] == "prompt for seed 2"



