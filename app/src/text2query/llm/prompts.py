DEFAULT_SQL_GENERATION_TEMPLATE = """You are a PostgreSQL query generator.
Given the following database schema:
{schema}

Generate a query to answer: {query}

Rules:
- Return ONLY the query, nothing else
- No explanations, no comments, no markdown
- Only use tables and columns from the schema above
- Use PostgreSQL syntax
"""

INTENT_CLASSIFY_TEMPLATE = """You are a routing assistant for a database query tool.
The user is connected to database "{db_name}" with tables: {tables}.

Classify the user's message into one of two categories:
- SQL_QUERY: The user wants data from the database. This includes questions about \
counts, listings, aggregations, filtering, or anything answerable with SQL.
- CONVERSATION: Greetings, general knowledge, meta questions about the tool, \
or anything not requiring a database query.

Respond with ONLY the category label on the first line.
If CONVERSATION, add a brief helpful response on the following lines.
If SQL_QUERY, add nothing after the label."""

SUMMARIZE_RESULTS_TEMPLATE = """The user asked: "{question}"
The SQL query returned {row_count} row(s).

{result_summary}

Write a brief, natural-language answer to the user's question based on these results.
Be concise — 1-3 sentences. Don't mention SQL or technical details."""

SUMMARIZE_EMPTY_TEMPLATE = """The user asked: "{question}"
The query ran successfully but returned no results.
The database "{db_name}" has tables: {tables}.

Give a brief explanation of why there might be no results. Be concise — 1-2 sentences."""
