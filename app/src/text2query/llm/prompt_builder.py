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

_PLANNING = (
    "Before writing the query: list the relevant tables and the join path as SQL "
    "comments (lines starting with --). Then write the final SQL query."
)


# Static, schema-agnostic pairs (Spider-style; deliberately NOT TPC-H tables,
# so small models can't copy structure instead of reading the user's question).
FEW_SHOT_EXAMPLES: list[tuple[str, str]] = [
    (
        "How many singers are there?",
        "SELECT COUNT(*) FROM singer;",
    ),
    (
        "List each department's name and its number of employees, largest first.",
        "SELECT d.dept_name, COUNT(e.emp_id) AS num_employees\n"
        "FROM department d JOIN employee e ON e.dept_id = d.dept_id\n"
        "GROUP BY d.dept_name ORDER BY num_employees DESC;",
    ),
    (
        "Show the titles of courses with more students enrolled than the average enrollment.",
        "SELECT title FROM course\n"
        "WHERE enrollment > (SELECT AVG(enrollment) FROM course);",
    ),
]


def _examples_section(n: int) -> str:
    blocks = (f"Question: {q}\nSQL: {sql}" for q, sql in FEW_SHOT_EXAMPLES[:n])
    return "Example question-to-SQL conversions (from other databases):\n\n" + "\n\n".join(blocks)


def _wrap(tag: str | None, body: str, xml: bool) -> str:
    return f"<{tag}>\n{body}\n</{tag}>" if xml and tag else body


def build_prompt(flags: PromptFlags, schema_str: str, question: str) -> str:
    rules = _RULES_MINIMAL + (f"\n{_RULES_STRICT}" if flags.strict_output else "")
    sections: list[tuple[str | None, str]] = [
        (None, _ROLE),
        ("schema", f"Given the following database schema:\n{schema_str}"),
    ]
    if flags.few_shot > 0:
        sections.append(("examples", _examples_section(flags.few_shot)))
    if flags.planning:
        sections.append((None, _PLANNING))
    sections.append(("query", f"Generate a query to answer: {question}"))
    sections.append(("rules", rules))
    return "\n\n".join(_wrap(tag, body, flags.xml_structure) for tag, body in sections)
