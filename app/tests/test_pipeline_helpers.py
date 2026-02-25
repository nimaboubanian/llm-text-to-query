from pathlib import Path

from text2query.benchmark.pipeline import _parse_schema_sql
from text2query.benchmark.data_loader import _fmt_size

import pytest


class TestParseSchemaSQL:
    def test_splits_statements(self, tmp_path):
        schema = tmp_path / "schema.sql"
        schema.write_text("CREATE TABLE a (id INT);\nCREATE TABLE b (id INT);")
        stmts = _parse_schema_sql(schema)
        assert len(stmts) == 2
        assert stmts[0].startswith("CREATE TABLE a")

    def test_strips_comments(self, tmp_path):
        schema = tmp_path / "schema.sql"
        schema.write_text("-- header comment\nCREATE TABLE t (x INT);")
        stmts = _parse_schema_sql(schema)
        assert len(stmts) == 1
        assert "--" not in stmts[0]

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            _parse_schema_sql(Path("/no/such/file.sql"))

    def test_skips_blank_statements(self, tmp_path):
        schema = tmp_path / "schema.sql"
        schema.write_text("CREATE TABLE x (id INT);\n\n;\n\n")
        stmts = _parse_schema_sql(schema)
        assert len(stmts) == 1


def test_fmt_size_bytes():
    assert _fmt_size(512) == "512.0 B"


def test_fmt_size_megabytes():
    assert _fmt_size(2 * 1024 * 1024) == "2.0 MB"


def test_fmt_size_gigabytes():
    assert _fmt_size(3 * 1024 ** 3) == "3.0 GB"
