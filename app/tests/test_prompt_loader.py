import pytest

from text2query.benchmark.fingerprint import GenerationFingerprint
from text2query.llm.prompt_loader import (
    MAX_TEMPLATE_SIZE,
    PromptTemplateError,
    load_prompt_template,
    render_prompt,
)


def test_missing_file_raises(tmp_path):
    with pytest.raises(PromptTemplateError, match="Could not read"):
        load_prompt_template(tmp_path / "nope.txt")


def test_missing_placeholder_raises(tmp_path):
    path = tmp_path / "template.txt"
    path.write_text("Schema: {schema}\nNo question placeholder here.")

    with pytest.raises(PromptTemplateError, match=r"\{query\}"):
        load_prompt_template(path)


def test_oversized_template_raises(tmp_path):
    path = tmp_path / "template.txt"
    path.write_text("{schema} {query} " + "x" * MAX_TEMPLATE_SIZE)

    with pytest.raises(PromptTemplateError, match="exceeds"):
        load_prompt_template(path)


def test_valid_template_loads(tmp_path):
    path = tmp_path / "template.txt"
    path.write_text("Schema: {schema}\nQuery: {query}\n")

    assert load_prompt_template(path) == "Schema: {schema}\nQuery: {query}\n"


def test_render_prompt_is_single_pass_and_inert():
    """Placeholder-like text inside schema/question must never be re-substituted."""
    template = "S:{schema}\nQ:{query}"
    schema = "TABLE t"
    question = "what about {schema} and {query}?"

    rendered = render_prompt(template, schema, question)

    assert rendered == "S:TABLE t\nQ:what about {schema} and {query}?"


def test_prompt_template_edit_changes_fingerprint(tmp_path):
    path = tmp_path / "template.txt"
    path.write_text("Schema: {schema}\nQuery: {query}\n")
    original = load_prompt_template(path)
    fp_before = GenerationFingerprint(
        model="m", prompt_template=original, schema="s",
        temperature=0.1, max_tokens=10, seed=None, flags={},
    ).hash

    path.write_text("Schema: {schema}\nQuery: {query}\nExtra rule.\n")
    edited = load_prompt_template(path)
    fp_after = GenerationFingerprint(
        model="m", prompt_template=edited, schema="s",
        temperature=0.1, max_tokens=10, seed=None, flags={},
    ).hash

    assert fp_before != fp_after
