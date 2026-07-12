import json

from text2query.benchmark.reporting import write_session_manifest, _redact_db_url
from text2query.benchmark.fingerprint import write_manifest, collect_fingerprints


def test_session_manifest_has_required_fields(tmp_path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    manifest_path = write_session_manifest(
        session_dir,
        models=["m1", "m2"],
        seeds=[1, 2],
        query_ids=["01", "02"],
        scale_factor=1,
        generation_parameters={"temperature": 0.1, "max_tokens": 2048, "num_ctx": 4096},
        fingerprints={".": "abc123"},
        database_url="postgresql://user:password@postgres:5432/testdb",
    )

    manifest = json.loads(manifest_path.read_text())
    assert "timestamp" in manifest
    assert "package_version" in manifest
    assert manifest["models"] == ["m1", "m2"]
    assert manifest["seeds"] == [1, 2]
    assert manifest["query_ids"] == ["01", "02"]
    assert manifest["scale_factor"] == 1
    assert manifest["generation_parameters"] == {"temperature": 0.1, "max_tokens": 2048, "num_ctx": 4096}
    assert manifest["fingerprints"] == {".": "abc123"}
    assert "database_url" in manifest


def test_session_manifest_strips_credentials(tmp_path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    manifest_path = write_session_manifest(
        session_dir,
        models=["m1"], seeds=None, query_ids=None, scale_factor=1,
        generation_parameters={}, fingerprints={},
        database_url="postgresql://user:password@postgres:5432/testdb",
    )

    manifest = json.loads(manifest_path.read_text())
    assert "user" not in manifest["database_url"]
    assert "password" not in manifest["database_url"]
    assert manifest["database_url"] == "postgresql://***:***@postgres:5432/testdb"


def test_redact_db_url_handles_url_without_credentials():
    assert _redact_db_url("postgresql://postgres:5432/testdb") == "postgresql://postgres:5432/testdb"


def test_collect_fingerprints_flat_layout(tmp_path):
    write_manifest(tmp_path, "fp-root", {"model": "m1"})
    assert collect_fingerprints(tmp_path) == {".": "fp-root"}


def test_collect_fingerprints_nested_layout(tmp_path):
    write_manifest(tmp_path / "seed_1", "fp-seed1", {"model": "m1"})
    write_manifest(tmp_path / "seed_2", "fp-seed2", {"model": "m1"})
    assert collect_fingerprints(tmp_path) == {"seed_1": "fp-seed1", "seed_2": "fp-seed2"}


def test_collect_fingerprints_missing_directory(tmp_path):
    assert collect_fingerprints(tmp_path / "does_not_exist") == {}
