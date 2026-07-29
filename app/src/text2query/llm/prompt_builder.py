"""Assembles the SQL-generation prompt from togglable sections.

Section order is fixed (salience order from the thesis research): role,
schema, examples, planning, question, rules. Flags add/remove/reshape
sections; they never reorder them.
"""
from text2query.core.config import PromptFlags

_ROLE = "You are a PostgreSQL query generator used for SQL-generation benchmarking."

_RULES_MINIMAL = "Use PostgreSQL syntax. Only use tables and columns from the schema above."


def build_prompt(flags: PromptFlags, schema_str: str, question: str) -> str:
    sections = [
        _ROLE,
        f"Given the following database schema:\n{schema_str}",
        f"Generate a query to answer: {question}",
        _RULES_MINIMAL,
    ]
    return "\n\n".join(sections)
