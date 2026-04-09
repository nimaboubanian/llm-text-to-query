#!/usr/bin/env python3

import sys

from text2query.database.schema import create_engine_for_database, get_database_schema_string
from text2query.database.executor import execute_sql_query
from text2query.llm.service import get_sql_from_llm_streaming, list_available_models
from text2query.core.config import DATABASE_URL, DEFAULT_MODEL
from text2query.cli.style import (
    BG_BASE, FG_CYAN, FG_MUTED, FG_RED, FG_YELLOW, FG_GREEN, FG_TEXT, BOLD, RESET,
    PROMPT, ERROR, WARN, SPINNER,
    rule, header, panel, out, write_spinner, clear_line,
    init_screen, set_scroll_region, cleanup_screen,
)


def print_help():
    out(f"  {BOLD}Commands{RESET}")
    out(rule())
    out(f"  {FG_CYAN}/help{RESET}     {FG_MUTED}Show this help{RESET}")
    out(f"  {FG_CYAN}/schema{RESET}   {FG_MUTED}Show database schema{RESET}")
    out(f"  {FG_CYAN}/model{RESET}    {FG_MUTED}Show or switch model  (/model <name>){RESET}")
    out(f"  {FG_CYAN}/exit{RESET}     {FG_MUTED}Exit{RESET}")


def print_result(result, max_rows: int = 100):
    if isinstance(result, str):
        out(f"  {FG_RED}{ERROR}{RESET} {result}")
        return

    if result.empty:
        out(f"  {FG_MUTED}(empty result set){RESET}")
        return

    count = len(result)
    label = f"{count} row{'s' if count != 1 else ''}"
    if count > max_rows:
        out(header("Results", f"showing {max_rows} of {count} rows"))
        out(result.head(max_rows).to_string(index=False))
        out(f"  {FG_MUTED}... ({count - max_rows} more rows){RESET}")
    else:
        out(header("Results", label))
        out(result.to_string(index=False))


def handle_schema(engine):
    from sqlalchemy import inspect as sa_inspect
    inspector = sa_inspect(engine)
    out(header("Database Schema"))
    for table in inspector.get_table_names():
        columns = inspector.get_columns(table)
        fks = inspector.get_foreign_keys(table)
        out(f"  {FG_CYAN}{table}{RESET}")
        for col in columns:
            out(f"    {col['name']}  {FG_MUTED}{col['type']}{RESET}")
        for fk in fks:
            cols = ", ".join(fk["constrained_columns"])
            out(f"    {FG_MUTED}{cols} → {fk['referred_table']}{RESET}")
        out()


def handle_query(question: str, engine, schema: str, model: str):
    generated_sql = None
    error = None
    spinner_idx = 0

    for chunk in get_sql_from_llm_streaming(question, schema, "postgresql", model):
        if chunk["type"] == "token":
            frame = SPINNER[spinner_idx % len(SPINNER)]
            write_spinner(f"  {FG_CYAN}{frame}{RESET} {FG_MUTED}Thinking...{RESET}")
            spinner_idx += 1
        elif chunk["type"] == "done":
            clear_line()
            generated_sql = chunk.get("sql")
            break
        elif chunk["type"] == "error":
            clear_line()
            error = chunk.get("message")
            break

    if error or not generated_sql:
        out(f"  {FG_RED}{ERROR}{RESET} Failed to generate SQL: {error or 'No SQL generated'}")
        return

    out(header("Generated SQL"))
    out(f"  {generated_sql}")
    out()

    result = execute_sql_query(engine, generated_sql)
    print_result(result)


def handle_model_command(args: str, current_model: str) -> str:
    """Handle /model command. Returns the (possibly changed) current model."""
    if not args:
        out(f"  {FG_MUTED}Current:{RESET} {FG_CYAN}{current_model}{RESET}")
        available = list_available_models()
        if available:
            out(f"  {FG_MUTED}Available:{RESET}")
            for m in available:
                if m == current_model:
                    out(f"    {FG_CYAN}{m}{RESET} {FG_MUTED}(active){RESET}")
                else:
                    out(f"    {m}")
        else:
            out(f"  {FG_YELLOW}{WARN}{RESET} Could not fetch available models from Ollama")
        return current_model

    # Switch to specified model
    target = args.strip()
    available = list_available_models()
    if available and target not in available:
        out(f"  {FG_YELLOW}{WARN}{RESET} Model '{target}' not found. Available: {', '.join(available)}")
        return current_model

    out(f"  {FG_GREEN}Switched to:{RESET} {target}")
    return target


def main():
    current_model = DEFAULT_MODEL

    # Initialize before entering alt screen — errors show in normal terminal
    try:
        engine = create_engine_for_database(DATABASE_URL)
    except Exception as e:
        print(f"Failed to connect to database: {e}")
        sys.exit(1)

    try:
        schema = get_database_schema_string(engine)
    except Exception as e:
        print(f"Failed to load schema: {e}")
        sys.exit(1)

    from sqlalchemy import inspect as sa_inspect
    inspector = sa_inspect(engine)
    tables = inspector.get_table_names()
    db_name = DATABASE_URL.rsplit("/", 1)[-1]

    init_screen()
    header_lines = [
        "",
        f"  {BOLD}{FG_TEXT}text2sql{RESET}",
        "",
        f"  {FG_MUTED}Model{RESET}   {FG_CYAN}{current_model}{RESET}",
        f"  {FG_MUTED}DB{RESET}      {FG_TEXT}{db_name}{RESET}  {FG_MUTED}·  {len(tables)} tables ({', '.join(tables)}){RESET}",
        "",
        f"  {FG_MUTED}/help · /schema · /model <name> · /exit{RESET}",
        "",
    ]
    panel(header_lines)
    set_scroll_region(len(header_lines) + 1)

    try:
        while True:
            try:
                user_input = input(f"{BG_BASE}  {FG_CYAN}{PROMPT}{RESET} ").strip()

                if not user_input:
                    continue

                if user_input in ("/exit", "/quit"):
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

                out()

            except KeyboardInterrupt:
                break
            except EOFError:
                break
            except Exception as e:
                out(f"  {FG_RED}{ERROR}{RESET} Unexpected error: {e}")
    finally:
        cleanup_screen()


if __name__ == "__main__":
    main()
