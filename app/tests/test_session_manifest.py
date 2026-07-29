import json

from text2query.benchmark.reporting import write_session_manifest, _redact_db_url


def test_session_manifest_strips_credentials(tmp_path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    manifest_path = write_session_manifest(
        session_dir,
        models=["m1"], seeds=None, query_ids=None, scale_factor=1,
        generation_parameters={}, prompt_flags={"schema_ddl": True}, fingerprints={},
        database_url="postgresql://user:password@postgres:5432/testdb",
    )

    manifest = json.loads(manifest_path.read_text())
    assert "user" not in manifest["database_url"]
    assert "password" not in manifest["database_url"]
    assert manifest["database_url"] == "postgresql://***:***@postgres:5432/testdb"
    assert manifest["prompt_flags"] == {"schema_ddl": True}


def test_redact_db_url_handles_url_without_credentials():
    assert _redact_db_url("postgresql://postgres:5432/testdb") == "postgresql://postgres:5432/testdb"
