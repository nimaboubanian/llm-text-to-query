#!/usr/bin/env python3

import sys

from text2query.database.schema import create_engine_for_database, get_database_schema_string
from text2query.database.executor import execute_sql_query
from text2query.llm.service import get_sql_from_llm_streaming, list_available_models
from text2query.core.config import DATABASE_URL, DEFAULT_MODEL, FRONTDESK_MODEL
from text2query.cli.frontdesk import quick_classify, classify_intent, summarize_results
from text2query.cli.style import (
    BG_BASE, FG_CYAN, FG_FROST, FG_MUTED, FG_RED, FG_YELLOW, FG_GREEN, FG_TEXT, BOLD, RESET,
    PROMPT, ERROR, WARN, SPINNER, FULL_RESET,
    rule, header, panel, out, write_spinner, clear_line,
    init_screen, highlight_sql, format_table,
)


def print_help():
    out(f"  {BOLD}Commands{RESET}")
    out(rule())
    out(f"  {FG_CYAN}/help{RESET}     {FG_MUTED}Show this help{RESET}")
    out(f"  {FG_CYAN}/schema{RESET}   {FG_MUTED}Show database schema{RESET}")
    out(f"  {FG_CYAN}/model{RESET}    {FG_MUTED}Show or switch model  (/model <name>){RESET}")
    out(f"  {FG_CYAN}/sql{RESET}      {FG_MUTED}Toggle SQL display in results{RESET}")
    out(f"  {FG_CYAN}/exit{RESET}     {FG_MUTED}Exit{RESET}")


def print_result(result, max_rows: int = 20):
    if isinstance(result, str):
        out(f"  {FG_RED}{ERROR}{RESET} {result}")
        return

    if result.empty:
        out(f"  {FG_MUTED}(empty result set){RESET}")
        return

    count = len(result)
    row_label = f"{count} row{'s' if count != 1 else ''}"
    if count > max_rows:
        row_label = f"showing {max_rows} of {count} rows"
    out(f"  {FG_MUTED}Result  {row_label}{RESET}")
    out(format_table(result, max_rows))


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


def handle_query(
    question: str, engine, schema: str, model: str,
    show_sql: bool = True,
    frontdesk_model: str | None = None,
    db_name: str | None = None,
    tables: list[str] | None = None,
):
    generated_sql = None
    error = None
    spinner_idx = 0

    for chunk in get_sql_from_llm_streaming(question, schema, model):
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

    if show_sql:
        out(f"  {FG_MUTED}SQL{RESET}")
        for line in generated_sql.split('\n'):
            out(f"    {FG_TEXT}{highlight_sql(line)}{RESET}")
        out()

    result = execute_sql_query(engine, generated_sql)

    if frontdesk_model and db_name and tables:
        if show_sql:
            print_result(result)
        write_spinner(f"  {FG_CYAN}{SPINNER[0]}{RESET} {FG_MUTED}Summarizing...{RESET}")
        summary = summarize_results(question, result, db_name, tables, frontdesk_model)
        clear_line()
        if summary:
            out()
            for line in summary.split('\n'):
                out(f"  {FG_FROST}{line}{RESET}")
        elif not show_sql:
            # Summarization failed — fall back to raw table
            print_result(result)
    else:
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
    show_sql = False

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

    # Check front-desk model availability
    frontdesk_model = FRONTDESK_MODEL
    available = list_available_models()
    if available and frontdesk_model not in available:
        frontdesk_model = None

    init_screen()

    if frontdesk_model:
        assist_line = f"  {FG_MUTED}Assist{RESET}  {FG_CYAN}{frontdesk_model}{RESET}"
    else:
        assist_line = f"  {FG_MUTED}Assist  (unavailable){RESET}"

    header_lines = [
        "",
        f"  {BOLD}{FG_TEXT}text2sql{RESET}",
        "",
        f"  {FG_MUTED}Model{RESET}   {FG_CYAN}{current_model}{RESET}",
        assist_line,
        f"  {FG_MUTED}DB{RESET}      {FG_TEXT}{db_name}{RESET}",
        "",
        f"  {FG_MUTED}/help · /schema · /model <name> · /sql · /exit{RESET}",
        "",
    ]
    panel(header_lines)

    if not frontdesk_model:
        out(f"  {FG_YELLOW}{WARN}{RESET} Front-desk model not available. Running in direct SQL mode.")
        out()

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
                elif user_input == "/sql":
                    show_sql = not show_sql
                    state = f"{FG_GREEN}on{RESET}" if show_sql else f"{FG_MUTED}off{RESET}"
                    out(f"  SQL display: {state}")
                else:
                    if frontdesk_model:
                        quick = quick_classify(user_input, tables)
                        if quick == "sql":
                            handle_query(user_input, engine, schema, current_model,
                                         show_sql, frontdesk_model, db_name, tables)
                        elif quick == "conversation":
                            write_spinner(f"  {FG_CYAN}{SPINNER[0]}{RESET} {FG_MUTED}Routing...{RESET}")
                            _, response = classify_intent(user_input, db_name, tables, frontdesk_model)
                            clear_line()
                            out(f"  {FG_FROST}{response or 'I can help you query this database.'}{RESET}")
                        else:
                            write_spinner(f"  {FG_CYAN}{SPINNER[0]}{RESET} {FG_MUTED}Routing...{RESET}")
                            intent, response = classify_intent(user_input, db_name, tables, frontdesk_model)
                            clear_line()
                            if intent == "conversation":
                                out(f"  {FG_FROST}{response or 'I can help you query this database.'}{RESET}")
                            else:
                                handle_query(user_input, engine, schema, current_model,
                                             show_sql, frontdesk_model, db_name, tables)
                    else:
                        handle_query(user_input, engine, schema, current_model, show_sql=True)

                out()
                out(rule())
                out()

            except KeyboardInterrupt:
                break
            except EOFError:
                break
            except Exception as e:
                out(f"  {FG_RED}{ERROR}{RESET} Unexpected error: {e}")
    finally:
        sys.stdout.write(FULL_RESET + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
