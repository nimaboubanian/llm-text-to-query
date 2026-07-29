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
    out = render_schema(_engine(), PromptFlags(schema_fk=True))
    assert "Table 'orders': o_orderkey (INTEGER), o_status (CHAR(1))" in out
    assert "FK(l_orderkey) -> orders" in out  # legacy FK notation when flag enabled


def test_ddl_mode_emits_create_table():
    out = render_schema(_engine(), PromptFlags(schema_ddl=True))
    assert "CREATE TABLE orders (" in out
    assert "o_orderkey INTEGER" in out
    assert "PRIMARY KEY (o_orderkey)" in out
    assert "REFERENCES" not in out  # FK is a separate flag (Task 3)


def test_fk_flag_controls_prose_fk_notation():
    assert "FK(" not in render_schema(_engine(), PromptFlags())
    assert "FK(l_orderkey) -> orders" in render_schema(_engine(), PromptFlags(schema_fk=True))


def test_fk_flag_adds_references_in_ddl():
    out = render_schema(_engine(), PromptFlags(schema_ddl=True, schema_fk=True))
    assert "l_orderkey INTEGER REFERENCES orders(o_orderkey)" in out


def test_descriptions_flag_appends_comment_from_metadata():
    meta = {"orders": {"o_status": {"desc": "order status flag"}}}
    out = render_schema(_engine(), PromptFlags(schema_descriptions=True), metadata=meta)
    assert "o_status (CHAR(1)) [order status flag]" in out
    out_off = render_schema(_engine(), PromptFlags(), metadata=meta)
    assert "order status flag" not in out_off


def test_unknown_columns_degrade_gracefully():
    out = render_schema(_engine(), PromptFlags(schema_descriptions=True), metadata={})
    assert "[" not in out  # no enrichment markers at all


def test_samples_flag_appends_values():
    meta = {"orders": {"o_status": {"desc": "status", "samples": ["'O' (open)", "'F' (fulfilled)"]}}}
    out = render_schema(_engine(), PromptFlags(schema_samples=True), metadata=meta)
    assert "values: 'O' (open), 'F' (fulfilled)" in out
    assert "values:" not in render_schema(_engine(), PromptFlags(), metadata=meta)


def test_desc_and_samples_combine_with_semicolon():
    meta = {"orders": {"o_status": {"desc": "status", "samples": ["'O'"]}}}
    out = render_schema(
        _engine(), PromptFlags(schema_descriptions=True, schema_samples=True), metadata=meta
    )
    assert "[status; values: 'O']" in out
