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


def test_xml_structure_wraps_sections_in_order():
    flags = replace(BASELINE, xml_structure=True)
    prompt = build_prompt(flags, "SCHEMA_TEXT", "QUESTION_TEXT")
    assert "<schema>\nGiven the following database schema:\nSCHEMA_TEXT\n</schema>" in prompt
    assert "<query>\nGenerate a query to answer: QUESTION_TEXT\n</query>" in prompt
    assert "<rules>\nUse PostgreSQL syntax" in prompt and prompt.rstrip().endswith("</rules>")
    assert prompt.index("<schema>") < prompt.index("<query>") < prompt.index("<rules>")
    assert "<" not in build_prompt(BASELINE, "S", "Q")  # baseline untouched


def test_few_shot_inserts_n_examples_between_schema_and_question():
    flags = replace(BASELINE, few_shot=2)
    prompt = build_prompt(flags, "S", "Q")
    assert prompt.count("Question:") == 2 and prompt.count("SQL:") == 2
    assert prompt.index("S") < prompt.index("Question:") < prompt.index("Generate a query")


def test_few_shot_zero_means_no_examples():
    assert "Question:" not in build_prompt(BASELINE, "S", "Q")


def test_few_shot_examples_avoid_tpch_tables():
    from text2query.llm.prompt_builder import FEW_SHOT_EXAMPLES
    tpch = ("lineitem", "orders", "customer", "supplier", "partsupp", "nation", "region")
    assert len(FEW_SHOT_EXAMPLES) == 3
    for _, sql in FEW_SHOT_EXAMPLES:
        assert not any(t in sql.lower() for t in tpch)
