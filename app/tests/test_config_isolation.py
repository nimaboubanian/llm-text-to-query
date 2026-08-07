"""The benchmark database must be unreachable from configuration.

The benchmark pipeline drops and rebuilds its database, so no environment
variable may be able to aim it at a user's data.
"""
import importlib

import pytest

import backend.core.config as config


@pytest.fixture
def reloaded_config(monkeypatch):
    """Reload config under a patched environment, then restore the pristine module.

    A value of None deletes the variable instead of setting it.
    """
    def _load(**env):
        for key, value in env.items():
            monkeypatch.delenv(key, raising=False) if value is None else monkeypatch.setenv(key, value)
        return importlib.reload(config)

    yield _load
    # Undo the env patches *before* the restoring reload, or the restored module
    # would be rebuilt from the patched environment.
    monkeypatch.undo()
    importlib.reload(config)


def test_benchmark_database_url_targets_tpch():
    assert config.BENCHMARK_DATABASE_URL == "postgresql://user:password@postgres:5432/tpch"


def test_benchmark_database_url_ignores_the_environment(reloaded_config):
    cfg = reloaded_config(
        BENCHMARK_DATABASE_URL="postgresql://user:password@elsewhere:5432/victim",
        INTERACTIVE_APP_DATABASE_URL="postgresql://user:password@elsewhere:5432/victim",
    )
    assert cfg.BENCHMARK_DATABASE_URL == "postgresql://user:password@postgres:5432/tpch"
    assert "victim" not in cfg.BENCHMARK_DATABASE_URL


def test_interactive_app_database_url_is_user_configurable(reloaded_config):
    cfg = reloaded_config(INTERACTIVE_APP_DATABASE_URL="postgresql://u:p@192.168.1.10:5432/mydb")
    assert cfg.INTERACTIVE_APP_DATABASE_URL == "postgresql://u:p@192.168.1.10:5432/mydb"


def test_interactive_app_database_url_defaults_to_appdb(reloaded_config):
    cfg = reloaded_config(INTERACTIVE_APP_DATABASE_URL=None)
    assert cfg.INTERACTIVE_APP_DATABASE_URL == "postgresql://user:password@postgres:5432/appdb"


def test_benchmark_models_has_a_default(reloaded_config):
    cfg = reloaded_config(BENCHMARK_MODELS=None)
    assert cfg.BENCHMARK_MODELS == ["qwen2.5-coder:7b"]


def test_interactive_app_model_has_a_default(reloaded_config):
    cfg = reloaded_config(INTERACTIVE_APP_MODEL=None)
    assert cfg.INTERACTIVE_APP_MODEL == "qwen2.5-coder:7b"


def test_old_mode_ambiguous_names_are_gone():
    assert not hasattr(config, "DATABASE_URL")
    assert not hasattr(config, "DEFAULT_MODEL")
