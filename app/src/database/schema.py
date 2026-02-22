"""Database schema introspection via SQLAlchemy."""

from typing import Optional

from sqlalchemy import create_engine, inspect, text


def get_database_schema_string(engine) -> str:
    """Get schema string for LLM context."""
    inspector = inspect(engine)
    lines = []
    for table in inspector.get_table_names():
        cols = ", ".join(f"{c['name']} ({c['type']})" for c in inspector.get_columns(table))
        fks = [f"FK({','.join(fk['constrained_columns'])}) -> {fk['referred_table']}" 
               for fk in inspector.get_foreign_keys(table)]
        line = f"Table '{table}': {cols}"
        if fks:
            line += f". {' '.join(fks)}"
        lines.append(line)
    return "\n".join(lines)


def create_engine_for_database(db_url: str):
    """Create SQLAlchemy engine with connection pooling."""
    return create_engine(db_url, pool_pre_ping=True, pool_size=5, max_overflow=10, pool_recycle=3600)


def validate_database_connection(db_url: str) -> tuple[bool, Optional[str]]:
    """Test database connection. Returns (success, error_message)."""
    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True, None
    except Exception as e:
        return False, str(e)
