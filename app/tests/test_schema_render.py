from sqlalchemy import create_engine, text

from text2query.core.config import PromptFlags
from text2query.database.schema import render_schema


def _engine():
    e = create_engine("sqlite://")
    with e.begin() as c:
        c.execute(text("CREATE TABLE orders (o_orderkey INTEGER PRIMARY KEY, o_status CHAR(1))"))
        c.execute(text(
            "CREATE TABLE lineitem (l_orderkey INTEGER REFERENCES orders(o_orderkey), "
            "l_qty DECIMAL)"
        ))
    return e


def test_prose_mode_matches_legacy_format():
    out = render_schema(_engine(), PromptFlags())
    assert "Table 'orders': o_orderkey (INTEGER), o_status (CHAR(1))" in out
    assert "FK(l_orderkey) -> orders" in out  # legacy FK notation kept until Task 3


def test_ddl_mode_emits_create_table():
    out = render_schema(_engine(), PromptFlags(schema_ddl=True))
    assert "CREATE TABLE orders (" in out
    assert "o_orderkey INTEGER" in out
    assert "PRIMARY KEY (o_orderkey)" in out
    assert "REFERENCES" not in out  # FK is a separate flag (Task 3)
