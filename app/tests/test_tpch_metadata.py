"""Contract + accuracy check for tpch_metadata.json.

Shape checks always run. Domain checks compare the "all N values listed"
claims against the real TPC-H data files, and skip when those aren't present.
"""
from pathlib import Path

import pytest

from backend.database.schema import load_tpch_metadata

# tbl files are the raw TPC-H dbgen output: pipe-separated, spec column order.
SF1 = Path(__file__).resolve().parents[1] / "tpch" / "data" / "sf1"

SPEC_COLUMNS = {"region": 3, "nation": 4, "supplier": 7, "customer": 8,
                "part": 9, "partsupp": 5, "orders": 9, "lineitem": 16}

# column -> (table, 1-based field index in that table's .tbl)
EXHAUSTIVE = {
    "r_name": ("region", 2),
    "c_mktsegment": ("customer", 7),
    "o_orderstatus": ("orders", 3),
    "o_orderpriority": ("orders", 6),
    "l_returnflag": ("lineitem", 9),
    "l_linestatus": ("lineitem", 10),
    "l_shipinstruct": ("lineitem", 14),
    "l_shipmode": ("lineitem", 15),
}


def test_shape_matches_consumer_contract():
    """schema._column_comment reads only .desc (str) and .samples (list[str])."""
    meta = load_tpch_metadata()
    assert set(meta) == set(SPEC_COLUMNS)
    for table, cols in meta.items():
        assert len(cols) == SPEC_COLUMNS[table], table
        for col, info in cols.items():
            assert set(info) <= {"desc", "samples"}, f"{table}.{col}"
            assert isinstance(info.get("desc"), str) and info["desc"], f"{table}.{col}"
            samples = info.get("samples", [])
            assert isinstance(samples, list), f"{table}.{col}"
            assert all(isinstance(s, str) for s in samples), f"{table}.{col}"


@pytest.mark.parametrize("column", sorted(EXHAUSTIVE))
def test_exhaustive_domains_match_real_data(column):
    """A column whose desc claims a complete list must actually list every value."""
    table, field = EXHAUSTIVE[column]
    tbl = SF1 / f"{table}.tbl"
    if not tbl.exists():
        pytest.skip(f"{tbl} not present")

    with tbl.open(encoding="utf-8") as fh:  # lineitem.tbl is ~760MB, stream it
        actual = {line.split("|")[field - 1] for line in fh if line.strip()}

    info = load_tpch_metadata()[table][column]
    assert "listed" in info["desc"], f"{column} lost its exhaustiveness claim"
    # samples carry SQL quotes and may append a gloss: "'O' (open)" -> O
    claimed = {s.split("'")[1] for s in info["samples"]}
    assert claimed == actual, f"{column}: metadata {claimed} != data {actual}"
