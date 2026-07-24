from unittest.mock import MagicMock, patch

from text2query.benchmark.data_loader import TPCH_TABLES, load_tpch_data


def test_load_tpch_data_invokes_item_callbacks(tmp_path):
    for table in TPCH_TABLES:
        (tmp_path / f"{table}.tbl").write_text("1|2|3|\n")

    fake_cursor = MagicMock()
    fake_cursor.rowcount = 1
    fake_conn = MagicMock()
    fake_conn.connection.cursor.return_value = fake_cursor
    fake_engine = MagicMock()
    fake_engine.begin.return_value.__enter__.return_value = fake_conn
    fake_engine.begin.return_value.__exit__.return_value = False

    starts = []
    outcomes = []

    with patch(
        "text2query.database.schema.create_engine_for_database", return_value=fake_engine
    ), patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value.wait.return_value = None
        mock_popen.return_value.returncode = 0
        mock_popen.return_value.stdout = None

        loaded = load_tpch_data(
            tmp_path, "postgresql://fake",
            on_item_start=lambda i, total, label: starts.append((i, total, label)),
            on_item_done=lambda outcome: outcomes.append(outcome),
        )

    assert loaded == {t: 1 for t in TPCH_TABLES}
    assert [s[:2] for s in starts] == [(i, len(TPCH_TABLES)) for i in range(1, len(TPCH_TABLES) + 1)]
    assert outcomes == [" ✓ 1 rows"] * len(TPCH_TABLES)
