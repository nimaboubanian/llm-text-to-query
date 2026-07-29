from text2query.database.schema import load_tpch_metadata

TPCH_COLUMN_PREFIX = {
    "region": "r_", "nation": "n_", "supplier": "s_", "customer": "c_",
    "part": "p_", "partsupp": "ps_", "orders": "o_", "lineitem": "l_",
}


def test_metadata_covers_all_eight_tpch_tables():
    meta = load_tpch_metadata()
    assert set(meta) == set(TPCH_COLUMN_PREFIX)


def test_metadata_keys_look_like_real_tpch_columns():
    meta = load_tpch_metadata()
    for table, cols in meta.items():
        for col, info in cols.items():
            assert col.startswith(TPCH_COLUMN_PREFIX[table]), f"{table}.{col}"
            assert info.get("desc"), f"{table}.{col} missing desc"
