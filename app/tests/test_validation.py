from pathlib import Path

from text2query.benchmark.validation import (
    check_directory,
    check_data_cache,
    check_answers_completeness,
)

import pytest


def test_check_directory_passes(tmp_path):
    for i in range(3):
        (tmp_path / f"q{i}.sql").write_text(f"SELECT {i}")
    check_directory(tmp_path, "sql", 3)  # should not raise


def test_check_directory_wrong_count(tmp_path):
    (tmp_path / "only.sql").write_text("SELECT 1")
    with pytest.raises(ValueError, match="Expected 5"):
        check_directory(tmp_path, "sql", 5)


def test_check_directory_missing_dir():
    with pytest.raises(FileNotFoundError):
        check_directory(Path("/nonexistent/dir"), "md", 1)


def test_data_cache_all_present(tmp_path):
    from text2query.benchmark.data_loader import TPCH_TABLES
    for t in TPCH_TABLES:
        (tmp_path / f"{t}.tbl").write_text("dummy data")
    assert check_data_cache(tmp_path) is True


def test_data_cache_missing_file(tmp_path):
    (tmp_path / "region.tbl").write_text("data")
    assert check_data_cache(tmp_path) is False


def test_answers_completeness_with_gap(tmp_path):
    queries_dir = tmp_path / "queries"
    answers_dir = tmp_path / "answers"
    queries_dir.mkdir()
    answers_dir.mkdir()

    for n in ("01", "02", "03"):
        (queries_dir / f"{n}.sql").write_text("SELECT 1")

    (answers_dir / "01.csv").write_text("id\n1\n")
    (answers_dir / "02.csv").write_text("id\n2\n")

    complete, missing = check_answers_completeness(answers_dir, queries_dir)
    assert complete is False
    assert missing == {"03"}
