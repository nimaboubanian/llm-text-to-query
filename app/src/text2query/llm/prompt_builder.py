"""Assembles the SQL-generation prompt from togglable sections.

Section order is fixed (salience order from the thesis research): role,
schema, examples, planning, question, rules. Flags add/remove/reshape
sections; they never reorder them.
"""
from text2query.core.config import PromptFlags

_ROLE = "You are a PostgreSQL query generator used for SQL-generation benchmarking."

_RULES_MINIMAL = "Use PostgreSQL syntax. Only use tables and columns from the schema above."

_RULES_STRICT = (
    "Return ONLY the SQL query, nothing else.\n"
    "No explanations, no comments, no markdown."
)


def _wrap(tag: str | None, body: str, xml: bool) -> str:
    if xml and tag:
        return f"<{tag}>\n{body}\n</{tag}>"
    return body


def build_prompt(flags: PromptFlags, schema_str: str, question: str) -> str:
    rules = _RULES_MINIMAL + (f"\n{_RULES_STRICT}" if flags.strict_output else "")
    sections: list[tuple[str | None, str]] = [
        (None, _ROLE),
        ("schema", f"Given the following database schema:\n{schema_str}"),
        ("query", f"Generate a query to answer: {question}"),
        ("rules", rules),
    ]
    return "\n\n".join(_wrap(tag, body, flags.xml_structure) for tag, body in sections)
