import json
from functools import cache
from pathlib import Path

from sqlalchemy import create_engine, inspect

from text2query.core.config import PromptFlags


@cache
def load_tpch_metadata() -> dict:
    """Curated TPC-H column descriptions/samples, packaged with the app."""
    return json.loads(Path(__file__).with_name("tpch_metadata.json").read_text(encoding="utf-8"))


def render_schema(engine, flags: PromptFlags, metadata: dict | None = None,
                   include_tables: set[str] | None = None) -> str:
    """Render the DB schema for the prompt, shaped by the schema feature flags.

    include_tables: restrict to these table names (None = all tables).
    """
    inspector = inspect(engine)
    meta = metadata or {}
    tables = [t for t in inspector.get_table_names()
              if include_tables is None or t in include_tables]
    return (_render_ddl if flags.schema_ddl else _render_prose)(inspector, flags, meta, tables)


def _column_comment(table_meta: dict, col_name: str, flags: PromptFlags) -> str:
    """Enrichment text for one column ('' when flags/metadata provide nothing)."""
    info = table_meta.get(col_name, {})
    parts = []
    if flags.schema_descriptions and info.get("desc"):
        parts.append(info["desc"])
    if flags.schema_samples and info.get("samples"):
        parts.append("values: " + ", ".join(info["samples"]))
    return "; ".join(parts)


def _render_prose(inspector, flags: PromptFlags, meta: dict, tables: list[str]) -> str:
    lines = []
    for table in tables:
        table_meta = meta.get(table, {})
        cols = []
        for c in inspector.get_columns(table):
            comment = _column_comment(table_meta, c["name"], flags)
            cols.append(f"{c['name']} ({c['type']})" + (f" [{comment}]" if comment else ""))
        line = f"Table '{table}': {', '.join(cols)}"
        if flags.schema_fk:
            fks = [f"FK({','.join(fk['constrained_columns'])}) -> {fk['referred_table']}"
                   for fk in inspector.get_foreign_keys(table)]
            if fks:
                line += f". {' '.join(fks)}"
        lines.append(line)
    return "\n".join(lines)


def _render_ddl(inspector, flags: PromptFlags, meta: dict, tables: list[str]) -> str:
    stmts = []
    for table in tables:
        table_meta = meta.get(table, {})
        fk_targets: dict[str, str] = {}
        if flags.schema_fk:
            for fk in inspector.get_foreign_keys(table):
                for src, dst in zip(fk["constrained_columns"], fk["referred_columns"]):
                    fk_targets[src] = f"{fk['referred_table']}({dst})"
        entries = []
        for c in inspector.get_columns(table):
            decl = f"{c['name']} {c['type']}"
            if c["name"] in fk_targets:
                decl += f" REFERENCES {fk_targets[c['name']]}"
            entries.append((decl, _column_comment(table_meta, c["name"], flags)))
        pk = inspector.get_pk_constraint(table).get("constrained_columns")
        if pk:
            entries.append((f"PRIMARY KEY ({', '.join(pk)})", ""))
        lines = []
        for i, (decl, comment) in enumerate(entries):
            comma = "," if i < len(entries) - 1 else ""
            suffix = f" -- {comment}" if comment else ""
            lines.append(f"  {decl}{comma}{suffix}")
        stmts.append(f"CREATE TABLE {table} (\n" + "\n".join(lines) + "\n);")
    return "\n\n".join(stmts)


def create_engine_for_database(db_url: str):
    return create_engine(db_url, pool_pre_ping=True, pool_size=5, max_overflow=10, pool_recycle=3600)
