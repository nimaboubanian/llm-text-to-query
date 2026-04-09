"""Tests for REPL model switching."""
import re
from unittest.mock import patch

from text2query.cli.repl import handle_model_command

_ANSI_RE = re.compile(r'\033\[[0-9;]*m')


def strip_ansi(text):
    return _ANSI_RE.sub('', text)


def test_model_command_show_current(capsys):
    """No args shows current model."""
    result = handle_model_command("", "qwen2.5-coder:7b")
    assert result == "qwen2.5-coder:7b"
    output = strip_ansi(capsys.readouterr().out)
    assert "Current:" in output
    assert "qwen2.5-coder:7b" in output


def test_model_command_list_available(capsys):
    with patch("text2query.cli.repl.list_available_models", return_value=["model-a", "model-b"]):
        handle_model_command("", "model-a")
    output = strip_ansi(capsys.readouterr().out)
    assert "model-a" in output
    assert "model-b" in output
    assert "(active)" in output


def test_model_command_switch(capsys):
    with patch("text2query.cli.repl.list_available_models", return_value=["model-a", "model-b"]):
        result = handle_model_command("model-b", "model-a")
    assert result == "model-b"
    assert "Switched to:" in strip_ansi(capsys.readouterr().out)


def test_model_command_switch_not_found(capsys):
    with patch("text2query.cli.repl.list_available_models", return_value=["model-a"]):
        result = handle_model_command("nonexistent", "model-a")
    assert result == "model-a"  # unchanged
    assert "not found" in strip_ansi(capsys.readouterr().out)


def test_model_command_ollama_unavailable(capsys):
    """When Ollama can't be reached, switch anyway (trust the user)."""
    with patch("text2query.cli.repl.list_available_models", return_value=[]):
        result = handle_model_command("", "model-a")
    output = strip_ansi(capsys.readouterr().out)
    assert "Could not fetch" in output
