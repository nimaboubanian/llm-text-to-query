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


from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

from backend.benchmark.runner import (
    RATE_LIMIT_PROBE_SECONDS, QuotaExhausted, run_llm_generation,
)
from backend.benchmark.reporting import RATE_LIMITED_MARKER
from backend.llm.ollama import GenerationResult


def _questions(tmp_path: Path, *qids: str) -> Path:
    questions_dir = tmp_path / "questions"
    questions_dir.mkdir(exist_ok=True)
    for qid in qids:
        (questions_dir / f"{qid}.md").write_text(f'# Business Question:\n  "Question {qid}?"\n')
    return questions_dir


def _ok(sql: str = "SELECT 1;") -> GenerationResult:
    return GenerationResult(sql=sql, raw_response=sql, prompt="p")


def _rate_limited(reason: str = "session usage limit reached") -> GenerationResult:
    return GenerationResult(
        sql=None, prompt="p", status_code=429,
        error=f"Ollama Cloud rate limit hit (HTTP 429) for 'big-cloud': {reason}",
    )


@contextmanager
def _patched_runner(generate):
    """Patch out the DB/schema/warmup/sleep dependencies, wiring `generate` as the LLM.

    Yields the list of slept intervals, so a test can assert the probe waited without
    the suite ever actually sleeping.
    """
    import backend.benchmark.runner as runner_mod
    slept: list[float] = []
    with ExitStack() as stack:
        stack.enter_context(patch.object(runner_mod, "create_engine_for_database", lambda url: None))
        stack.enter_context(patch.object(
            runner_mod, "render_schema",
            lambda engine, flags, metadata=None, include_tables=None: "schema"))
        stack.enter_context(patch.object(runner_mod, "load_tpch_metadata", lambda: {}))
        stack.enter_context(patch.object(runner_mod.ollama, "warmup", lambda model: True))
        stack.enter_context(patch.object(runner_mod.ollama, "generate_sql_with_retry", generate))
        stack.enter_context(patch.object(runner_mod, "sleep", slept.append))
        yield slept


def test_a_transient_429_is_recovered_by_the_probe_retry(tmp_path):
    """Ollama Cloud returns 429 for its concurrency limit too, which clears in seconds.
    One probe must recover the run rather than discarding it."""
    questions_dir = _questions(tmp_path, "01", "02")
    output_dir = tmp_path / "out"
    calls = []

    def generate(question, schema, model, seed=None, validate=None):
        calls.append(question)
        # First query is refused once, then succeeds on the probe.
        return _rate_limited("too many concurrent requests") if len(calls) == 1 else _ok()

    with _patched_runner(generate) as slept:
        aborted = run_llm_generation(
            questions_dir, output_dir, "postgresql://fake", "big-cloud", seeds=[1],
        )

    assert aborted is False
    assert slept == [RATE_LIMIT_PROBE_SECONDS]
    # Both queries generated: 01 via the probe, 02 normally.
    assert (output_dir / "seed_1" / "01.sql").exists()
    assert (output_dir / "seed_1" / "02.sql").exists()
    assert not list((output_dir / "seed_1").glob("*.raw"))


def test_a_second_429_aborts_without_a_third_attempt(tmp_path):
    """A 429 that survives the probe means the usage budget really is spent — stop,
    rather than spending the rest of the run on requests that will all be refused."""
    questions_dir = _questions(tmp_path, "01", "02", "03")
    output_dir = tmp_path / "out"
    calls = []

    def generate(question, schema, model, seed=None, validate=None):
        calls.append(question)
        return _ok() if len(calls) == 1 else _rate_limited()

    with _patched_runner(generate) as slept:
        aborted = run_llm_generation(
            questions_dir, output_dir, "postgresql://fake", "big-cloud", seeds=[1],
        )

    assert aborted is True
    # 01 succeeded, 02 was refused twice (attempt + probe), 03 was never sent.
    assert len(calls) == 3
    assert slept == [RATE_LIMIT_PROBE_SECONDS]


def test_429_marks_the_current_seed_remaining_queries_as_rate_limited(tmp_path):
    """The 429 fires on query 02: 01 keeps its SQL, 02 and 03 get skip sentinels."""
    questions_dir = _questions(tmp_path, "01", "02", "03")
    output_dir = tmp_path / "out"
    calls = []

    def generate(question, schema, model, seed=None, validate=None):
        calls.append(question)
        return _ok() if len(calls) == 1 else _rate_limited()

    with _patched_runner(generate):
        aborted = run_llm_generation(
            questions_dir, output_dir, "postgresql://fake", "big-cloud", seeds=[1],
        )

    assert aborted is True
    seed1 = output_dir / "seed_1"
    assert (seed1 / "01.sql").exists()
    assert not (seed1 / "02.sql").exists()
    for qid in ("02", "03"):
        assert (seed1 / f"{qid}.raw").read_text().startswith(RATE_LIMITED_MARKER)


def test_the_sentinel_records_the_servers_stated_reason(tmp_path):
    """The one field that says *why* the run stopped must reach the report, not be
    replaced by our own guess at the cause."""
    questions_dir = _questions(tmp_path, "01")
    output_dir = tmp_path / "out"

    def generate(question, schema, model, seed=None, validate=None):
        return _rate_limited("weekly usage limit reached")

    with _patched_runner(generate):
        run_llm_generation(questions_dir, output_dir, "postgresql://fake", "big-cloud", seeds=[1])

    raw = (output_dir / "seed_1" / "01.raw").read_text()
    assert raw.startswith(RATE_LIMITED_MARKER)
    assert "weekly usage limit reached" in raw


def test_429_marks_the_seeds_that_never_started(tmp_path):
    questions_dir = _questions(tmp_path, "01", "02")
    output_dir = tmp_path / "out"

    def generate(question, schema, model, seed=None, validate=None):
        return _rate_limited()

    with _patched_runner(generate):
        aborted = run_llm_generation(
            questions_dir, output_dir, "postgresql://fake", "big-cloud", seeds=[1, 2, 3],
        )

    assert aborted is True
    for seed in (1, 2, 3):
        for qid in ("01", "02"):
            raw = output_dir / f"seed_{seed}" / f"{qid}.raw"
            assert raw.exists(), f"seed_{seed}/{qid}.raw missing"
            assert raw.read_text().startswith(RATE_LIMITED_MARKER)


def test_429_sentinels_respect_the_query_id_filter(tmp_path):
    """Only the queries this run was asked for get marked — not the whole question set."""
    questions_dir = _questions(tmp_path, "01", "02", "03")
    output_dir = tmp_path / "out"

    def generate(question, schema, model, seed=None, validate=None):
        return _rate_limited()

    with _patched_runner(generate):
        run_llm_generation(
            questions_dir, output_dir, "postgresql://fake", "big-cloud",
            seeds=[1, 2], query_ids=["01", "03"],
        )

    for seed in (1, 2):
        assert (output_dir / f"seed_{seed}" / "01.raw").exists()
        assert (output_dir / f"seed_{seed}" / "03.raw").exists()
        assert not (output_dir / f"seed_{seed}" / "02.raw").exists()


def test_a_completed_run_reports_no_abort_and_never_sleeps(tmp_path):
    questions_dir = _questions(tmp_path, "01")
    output_dir = tmp_path / "out"

    with _patched_runner(lambda *a, **kw: _ok()) as slept:
        aborted = run_llm_generation(
            questions_dir, output_dir, "postgresql://fake", "local:7b", seeds=[1],
        )

    assert aborted is False
    assert slept == []


def test_a_non_429_failure_neither_probes_nor_aborts(tmp_path):
    """Only a rate limit gets the probe. An ordinary generation failure is recorded and
    the run continues, exactly as before."""
    questions_dir = _questions(tmp_path, "01", "02")
    output_dir = tmp_path / "out"
    calls = []

    def generate(question, schema, model, seed=None, validate=None):
        calls.append(question)
        return GenerationResult(sql=None, prompt="p", status_code=500,
                                error="LLM API error: 500")

    with _patched_runner(generate) as slept:
        aborted = run_llm_generation(
            questions_dir, output_dir, "postgresql://fake", "local:7b", seeds=[1],
        )

    assert aborted is False
    assert len(calls) == 2      # one attempt each, no probe
    assert slept == []
    raw = (output_dir / "seed_1" / "01.raw").read_text()
    assert not raw.startswith(RATE_LIMITED_MARKER)


def test_a_rate_limited_query_is_retried_on_the_next_run(tmp_path):
    """The sentinel is a .raw with no .sql, so the existing .sql-keyed cache retries it."""
    questions_dir = _questions(tmp_path, "01", "02")
    output_dir = tmp_path / "out"
    attempt = {"n": 0}

    def first_pass(question, schema, model, seed=None, validate=None):
        attempt["n"] += 1
        return _ok() if attempt["n"] == 1 else _rate_limited()

    with _patched_runner(first_pass):
        run_llm_generation(questions_dir, output_dir, "postgresql://fake", "big-cloud", seeds=[1])

    resumed = []

    def second_pass(question, schema, model, seed=None, validate=None):
        resumed.append(question)
        return _ok("SELECT 2;")

    with _patched_runner(second_pass):
        aborted = run_llm_generation(
            questions_dir, output_dir, "postgresql://fake", "big-cloud", seeds=[1],
        )

    assert aborted is False
    # Only the skipped query was re-sent; 01's cached .sql was kept.
    assert len(resumed) == 1
    assert (output_dir / "seed_1" / "02.sql").read_text() == "SELECT 2;"
