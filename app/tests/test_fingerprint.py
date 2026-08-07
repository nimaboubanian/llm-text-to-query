import json
from dataclasses import asdict

from backend.benchmark.fingerprint import (
    GenerationFingerprint, read_manifest_fingerprint, write_manifest,
)


def _fp(**overrides):
    defaults = dict(
        model="m1", prompt_template="template", schema="schema",
        temperature=0.1, max_tokens=2048, seed=None,
    )
    defaults.update(overrides)
    return GenerationFingerprint(**defaults)


def test_identical_inputs_produce_identical_hash():
    assert _fp().hash == _fp().hash


def test_hash_changes_with_model():
    assert _fp(model="m1").hash != _fp(model="m2").hash


def test_hash_changes_with_prompt_template():
    assert _fp(prompt_template="a").hash != _fp(prompt_template="b").hash


def test_hash_changes_with_schema():
    assert _fp(schema="a").hash != _fp(schema="b").hash


def test_hash_changes_with_temperature():
    assert _fp(temperature=0.1).hash != _fp(temperature=0.9).hash


def test_hash_changes_with_max_tokens():
    assert _fp(max_tokens=100).hash != _fp(max_tokens=200).hash


def test_hash_changes_with_seed():
    assert _fp(seed=1).hash != _fp(seed=2).hash
    assert _fp(seed=None).hash != _fp(seed=1).hash


def test_manifest_round_trip(tmp_path):
    fp = _fp()
    write_manifest(tmp_path, fp.hash, asdict(fp))
    assert read_manifest_fingerprint(tmp_path) == fp.hash


def test_manifest_content_is_complete(tmp_path):
    fp = _fp(model="m1", seed=3)
    write_manifest(tmp_path, fp.hash, asdict(fp))

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["fingerprint"] == fp.hash
    assert manifest["model"] == "m1"
    assert manifest["seed"] == 3
    assert manifest["prompt_template"] == "template"
    assert manifest["schema"] == "schema"
    assert manifest["temperature"] == 0.1
    assert manifest["max_tokens"] == 2048


def test_missing_manifest_returns_none(tmp_path):
    assert read_manifest_fingerprint(tmp_path) is None


def test_corrupt_manifest_returns_none(tmp_path):
    (tmp_path / "manifest.json").write_text("not json")
    assert read_manifest_fingerprint(tmp_path) is None


def test_fingerprint_changes_when_questions_change():
    from backend.benchmark.fingerprint import GenerationFingerprint
    base = dict(model="m", prompt_template="t", schema="s",
                temperature=0.1, max_tokens=10, seed=1)
    a = GenerationFingerprint(**base, questions="hash-a")
    b = GenerationFingerprint(**base, questions="hash-b")
    assert a.hash != b.hash
