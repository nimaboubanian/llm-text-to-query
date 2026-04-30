from pathlib import Path

from text2query.benchmark.pipeline import _parse_schema_sql

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


