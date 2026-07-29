from dataclasses import replace

from text2query.core.config import PromptFlags
from text2query.llm.prompt_builder import build_prompt

BASELINE = PromptFlags()

EXPECTED_BASELINE = """You are a PostgreSQL query generator used for SQL-generation benchmarking.

Given the following database schema:
Table 'singer': name (VARCHAR)

Generate a query to answer: How many singers are there?

Use PostgreSQL syntax. Only use tables and columns from the schema above."""


def test_all_flags_default_off():
    flags = PromptFlags()
    assert flags == PromptFlags(
        schema_ddl=False, schema_fk=False, schema_descriptions=False,
        schema_samples=False, xml_structure=False, few_shot=0,
        planning=False, strict_output=False, retry_on_error=False,
    )


def test_baseline_prompt_pinned_verbatim():
    prompt = build_prompt(BASELINE, "Table 'singer': name (VARCHAR)", "How many singers are there?")
    assert prompt == EXPECTED_BASELINE


def test_flags_are_frozen():
    import dataclasses, pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        BASELINE.schema_ddl = True


def test_strict_output_appends_emphatic_rules():
    flags = replace(BASELINE, strict_output=True)
    prompt = build_prompt(flags, "S", "Q")
    assert prompt.endswith(
        "Use PostgreSQL syntax. Only use tables and columns from the schema above.\n"
        "Return ONLY the SQL query, nothing else.\n"
        "No explanations, no comments, no markdown."
    )
    assert "Return ONLY" not in build_prompt(BASELINE, "S", "Q")
