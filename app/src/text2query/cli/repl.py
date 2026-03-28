#!/usr/bin/env python3

import sys

from text2query.database.schema import create_engine_for_database, get_database_schema_string
from text2query.database.executor import execute_sql_query
from text2query.llm.service import get_sql_from_llm_streaming, list_available_models
from text2query.core.config import DATABASE_URL, DEFAULT_MODEL


def print_help():
    print("Available commands:")
    print("  /help     - Show this help")
    print("  /schema   - Display database schema")
    print("  /model    - Show current model and list available models")
    print("  /model X  - Switch to model X")
    print("  /quit     - Exit the REPL")
    print()


def print_result(result, max_rows: int = 100):
    if isinstance(result, str):
        print(f"Error: {result}")
        return

    if result.empty:
        print("(empty result set)")
        return

    if len(result) > max_rows:
        print(f"{len(result)} rows (showing first {max_rows}):")
        print(result.head(max_rows).to_string(index=False))
        print(f"... ({len(result) - max_rows} more rows)")
    else:
        print(f"{len(result)} row{'s' if len(result) != 1 else ''}:")
        print(result.to_string(index=False))


def handle_schema(engine):
    schema = get_database_schema_string(engine)
    print("Database Schema:")
    print(schema)


def handle_query(question: str, engine, schema: str, model: str):
    print(f"Processing: {question}")
    print()

    generated_sql = None
    error = None

    for chunk in get_sql_from_llm_streaming(question, schema, "postgresql", model):
        if chunk["type"] == "token":
            pass
        elif chunk["type"] == "done":
            generated_sql = chunk.get("sql")
            break
        elif chunk["type"] == "error":
            error = chunk.get("message")
            break

    if error or not generated_sql:
        print(f"Failed to generate SQL: {error or 'No SQL generated'}")
        return

    print(f"Generated SQL:")
    print(generated_sql)
    print()

    result = execute_sql_query(engine, generated_sql)
    print_result(result)


def handle_model_command(args: str, current_model: str) -> str:
    """Handle /model command. Returns the (possibly changed) current model."""
    if not args:
        # Show current model and list available
        print(f"  Current: {current_model}")
        available = list_available_models()
        if available:
            print("  Available:")
            for m in available:
                marker = " (active)" if m == current_model else ""
                print(f"    - {m}{marker}")
        else:
            print("  Could not fetch available models from Ollama")
        return current_model

    # Switch to specified model
    target = args.strip()
    available = list_available_models()
    if available and target not in available:
        print(f"  Model '{target}' not found. Available: {', '.join(available)}")
        return current_model

    print(f"  Switched to: {target}")
    return target


def main():
    current_model = DEFAULT_MODEL
    print(f"Text-to-SQL  model={current_model}  db={DATABASE_URL}")
    print()

    try:
        engine = create_engine_for_database(DATABASE_URL)
        print("Connected to database")
    except Exception as e:
        print(f"Failed to connect to database: {e}")
        sys.exit(1)

    try:
        schema = get_database_schema_string(engine)
        print("Loaded database schema")
    except Exception as e:
        print(f"Failed to load schema: {e}")
        sys.exit(1)

    print()
    print("Type your question or /help for commands.")
    print()

    while True:
        try:
            user_input = input("Query> ").strip()

            if not user_input:
                continue

            if user_input == "/quit":
                print("Goodbye!")
                break
            elif user_input == "/help":
                print_help()
            elif user_input == "/schema":
                handle_schema(engine)
            elif user_input.startswith("/model"):
                args = user_input[6:].strip()
                current_model = handle_model_command(args, current_model)
            else:
                handle_query(user_input, engine, schema, current_model)

            print()

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except EOFError:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
