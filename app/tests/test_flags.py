import json

from text2query.core.flags import GenerationFlags
from text2query.benchmark.fingerprint import GenerationFingerprint
from text2query.benchmark.reporting import write_session_manifest


def test_defaults_are_all_off():
    flags = GenerationFlags()
    assert flags == GenerationFlags(retry=False, chain_of_thought=False, self_correction=False)


def test_from_env_reads_truthy_values(monkeypatch):
    monkeypatch.setenv("FEATURE_RETRY", "true")
    monkeypatch.setenv("FEATURE_CHAIN_OF_THOUGHT", "1")
    monkeypatch.delenv("FEATURE_SELF_CORRECTION", raising=False)

    flags = GenerationFlags.from_env()

    assert flags.retry is True
    assert flags.chain_of_thought is True
    assert flags.self_correction is False


def test_from_env_rejects_unrecognized_values(monkeypatch):
    monkeypatch.setenv("FEATURE_RETRY", "maybe")
    assert GenerationFlags.from_env().retry is False


def test_flags_are_frozen():
    flags = GenerationFlags()
    try:
        flags.retry = True
        assert False, "GenerationFlags should be immutable"
    except AttributeError:
        pass


def test_to_dict_round_trip():
    flags = GenerationFlags(retry=True, chain_of_thought=False, self_correction=True)
    assert flags.to_dict() == {
        "retry": True,
        "chain_of_thought": False,
        "self_correction": True,
    }


def test_flag_flip_changes_generation_fingerprint():
    base_kwargs = dict(
        model="m1", prompt_template="t", schema="s",
        temperature=0.1, max_tokens=2048, seed=None,
    )
    off = GenerationFingerprint(**base_kwargs, flags=GenerationFlags().to_dict())
    on = GenerationFingerprint(**base_kwargs, flags=GenerationFlags(retry=True).to_dict())
    assert off.hash != on.hash


def test_flags_present_in_session_manifest(tmp_path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    manifest_path = write_session_manifest(
        session_dir,
        models=["m1"], seeds=None, query_ids=None, scale_factor=1,
        generation_parameters={}, fingerprints={},
        database_url="postgresql://user:password@postgres:5432/testdb",
        flags=GenerationFlags(chain_of_thought=True).to_dict(),
    )

    manifest = json.loads(manifest_path.read_text())
    assert manifest["flags"] == {
        "retry": False,
        "chain_of_thought": True,
        "self_correction": False,
    }


def test_flags_default_to_empty_dict_in_manifest(tmp_path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    manifest_path = write_session_manifest(
        session_dir,
        models=["m1"], seeds=None, query_ids=None, scale_factor=1,
        generation_parameters={}, fingerprints={},
        database_url="postgresql://user:password@postgres:5432/testdb",
    )

    manifest = json.loads(manifest_path.read_text())
    assert manifest["flags"] == {}
