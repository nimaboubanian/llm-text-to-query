#!/usr/bin/env python3
"""Interactive REPL for text-to-SQL queries."""

import sys

from database.schema import create_engine_for_database, get_database_schema_string
from database.executor import execute_sql_query
from llm.service import get_sql_from_llm_streaming
from core.config import DATABASE_URL, DEFAULT_MODEL


def print_banner():
    """Display welcome banner."""
    print("=" * 60)
    print("  LLM Text-to-SQL Query Interface")
    print("=" * 60)
    print(f"  Model: {DEFAULT_MODEL}")
    print(f"  Database: {DATABASE_URL}")
    print()


def print_help():
    """Display available commands."""
    print("Available commands:")
    print("  /help     - Show this help")
    print("  /schema   - Display database schema")
    print("  /quit     - Exit the REPL")
    print()


def print_result(result, max_rows: int = 100):
    """Display query result."""
    if isinstance(result, str):  # Error message
        print(f"❌ Error: {result}")
        return

    if result.empty:
        print("✓ Empty result set")
        return

    # Truncate if too many rows
    if len(result) > max_rows:
        print(f"📊 {len(result)} rows (showing first {max_rows}):")
        print(result.head(max_rows).to_string(index=False))
        print(f"... ({len(result) - max_rows} more rows)")
    else:
        print(f"📊 {len(result)} row{'s' if len(result) != 1 else ''}:")
        print(result.to_string(index=False))


def handle_schema(engine):
    """Display /schema command output."""
    schema = get_database_schema_string(engine)
    print("📋 Database Schema:")
    print(schema)


def handle_query(question: str, engine, schema: str, model: str):
    """Process a natural language question."""
    print(f"🤔 Processing: {question}")
    print()

    # Generate SQL via LLM
    generated_sql = None
    error = None

    for chunk in get_sql_from_llm_streaming(question, schema, "postgresql", model):
        if chunk["type"] == "token":
            # Optional: Show streaming progress (could add verbose flag)
            pass
        elif chunk["type"] == "done":
            generated_sql = chunk.get("sql")
            break
        elif chunk["type"] == "error":
            error = chunk.get("message")
            break

    if error or not generated_sql:
        print(f"❌ Failed to generate SQL: {error or 'No SQL generated'}")
        return

    print(f"💾 Generated SQL:")
    print(generated_sql)
    print()

    # Execute SQL
    result = execute_sql_query(engine, generated_sql)
    print_result(result)


def main():
    """Run the interactive REPL loop."""
    print_banner()
    print_help()

    # Connect to database
    try:
        engine = create_engine_for_database(DATABASE_URL)
        print("✅ Connected to database")
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
        sys.exit(1)

    # Get schema for LLM context
    try:
        schema = get_database_schema_string(engine)
        print("✅ Loaded database schema")
    except Exception as e:
        print(f"❌ Failed to load schema: {e}")
        sys.exit(1)

    print()
    print("Type your question or /help for commands.")
    print()

    # Main REPL loop
    while True:
        try:
            user_input = input("❓ Query> ").strip()

            if not user_input:
                continue

            # Handle commands
            if user_input == "/quit":
                print("👋 Goodbye!")
                break
            elif user_input == "/help":
                print_help()
            elif user_input == "/schema":
                handle_schema(engine)
            else:
                handle_query(user_input, engine, schema, DEFAULT_MODEL)

            print()

        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            break
        except EOFError:
            print("\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"❌ Unexpected error: {e}")


if __name__ == "__main__":
    main()
