import pytest

from text2query.llm.prompt_loader import PromptTemplateError, load_prompt_template, render_prompt


def test_missing_placeholder_raises(tmp_path):
    path = tmp_path / "template.txt"
    path.write_text("Schema: {schema}\nNo question placeholder here.")

    with pytest.raises(PromptTemplateError, match=r"\{query\}"):
        load_prompt_template(path)


def test_render_prompt_is_single_pass_and_inert():
    """Placeholder-like text inside schema/question must never be re-substituted."""
    template = "S:{schema}\nQ:{query}"
    schema = "TABLE t"
    question = "what about {schema} and {query}?"

    rendered = render_prompt(template, schema, question)

    assert rendered == "S:TABLE t\nQ:what about {schema} and {query}?"
