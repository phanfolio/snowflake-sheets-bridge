"""Live tests against a real Google Sheet. Opt-in: see tests/live/conftest.py.

Part 1 runs the real publish() and checks the conversion contract on cells read back from Google.
Part 2 checks, one by one, the Google behaviours that FakeSheets models but that were never verified.
If Part 2 fails, FakeSheets (and possibly the publish design) is wrong, not just a test.

Run:  GOOGLE_APPLICATION_CREDENTIALS=... SNOWSHEETS_LIVE_SHEET_ID=... uv run pytest -m live -v
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from fakes import assert_bi_ready, cell_kind, cell_value, number_format
from live_helpers import LIVE, live_client, read_grid, tab_name, tab_props  # noqa: F401 (fixtures)
from snowsheets import sheets
from snowsheets.config import STAGING_PREFIX
from snowsheets.sheets import SheetsApiError, publish
from snowsheets.snowflake_source import Table, normalize
from test_bi_contract import TYPE_MATRIX

pytestmark = LIVE
CST = timezone(timedelta(hours=-6))


# ============================================================ Part 1: the conversion contract
def test_every_snowflake_type_round_trips_through_real_sheets(live_client, tab_name):
    """One column per Snowflake type, so the whole type matrix costs a single publish."""
    params = [p.values for p in TYPE_MATRIX]
    header = [f"C{i:02d}_{p.id}"[:60] for i, p in enumerate(TYPE_MATRIX)]
    table = Table(header, [[normalize(raw) for raw, *_ in params],     # values
                           [normalize(None) for _ in params]])         # NULLs
    publish(live_client, [(tab_name, table)])

    grid = read_grid(live_client, tab_name)
    assert_bi_ready(grid, header, n_rows=2)
    for col, (raw, expected, kind, fmt) in enumerate(params):
        value_cell, null_cell = grid[1][col], grid[2][col]
        assert cell_value(value_cell) == expected, header[col]
        assert cell_kind(value_cell) == kind, header[col]
        assert number_format(value_cell) == fmt, header[col]
        assert cell_kind(null_cell) is None, header[col]


def test_realistic_table_is_bi_ready(live_client, tab_name):
    header = ["ORDER_DATE", "REGION", "REVENUE", "ORDERS", "IS_PROMO", "UPDATED_AT", "NOTE"]
    raw_rows = [
        (date(2026, 1, 1), "north", Decimal("1200.50"), 14, True,  datetime(2026, 1, 2, 3, tzinfo=CST), None),
        (date(2026, 1, 1), "south", Decimal("980.00"),  9,  False, datetime(2026, 1, 2, 4, tzinfo=CST), "promo"),
        (date(2026, 1, 2), None,    None,               0,  None,  None,                               None),
    ]
    publish(live_client, [(tab_name, Table(header, [[normalize(v) for v in r] for r in raw_rows]))])

    grid = read_grid(live_client, tab_name)
    assert_bi_ready(grid, header, n_rows=3)
    assert [number_format(grid[1][c]) for c in range(len(header))] == \
        ["DATE", None, None, None, None, "DATE_TIME", None]
    assert not tab_props(live_client, tab_name).get("hidden", False)


def test_republishing_leaves_no_stale_cells_or_formats(live_client, tab_name):
    publish(live_client, [(tab_name, Table(["A", "B", "C"], [[date(2026, 1, 1), "x", 1]] * 5))])
    publish(live_client, [(tab_name, Table(["A", "B"], [["now text", 2]]))])

    grid = read_grid(live_client, tab_name)
    assert_bi_ready(grid, ["A", "B"], n_rows=1)
    assert number_format(grid[1][0]) is None


def test_empty_result_publishes_a_header_only_table(live_client, tab_name):
    publish(live_client, [(tab_name, Table(["A", "B"], []))])
    assert_bi_ready(read_grid(live_client, tab_name), ["A", "B"], n_rows=0)


def test_chunked_writes_reassemble_correctly(live_client, tab_name, monkeypatch):
    monkeypatch.setattr(sheets, "MAX_REQUEST_BYTES", 2_000)          # force several staging requests
    rows = [[i, f"row {i}", date(2026, 1, 1)] for i in range(40)]
    publish(live_client, [(tab_name, Table(["N", "LABEL", "D"], rows))])

    grid = read_grid(live_client, tab_name)
    assert_bi_ready(grid, ["N", "LABEL", "D"], n_rows=40)
    assert [cell_value(r[0]) for r in grid[1:]] == list(range(40))


def test_publish_leaves_no_staging_tabs(live_client, tab_name):
    publish(live_client, [(tab_name, Table(["A"], [[1]]))])
    assert not [t for t in live_client.sheet_properties() if t["title"].startswith(STAGING_PREFIX)]


# ============================================================ Part 2: what FakeSheets assumes
def _add_tab(client, title, rows, cols):
    reply = client.batch_update([{"addSheet": {"properties": {
        "title": title, "gridProperties": {"rowCount": rows, "columnCount": cols}}}}])
    return reply[0]["addSheet"]["properties"]["sheetId"]


def _write(client, sheet_id, row, col, values):
    client.batch_update([{"updateCells": {
        "start": {"sheetId": sheet_id, "rowIndex": row, "columnIndex": col},
        "rows": [{"values": [{"userEnteredValue": {"stringValue": v}} for v in values]}],
        "fields": "userEnteredValue"}}])


def test_assumption_batch_update_is_all_or_nothing(live_client, tab_name):
    with pytest.raises(SheetsApiError):
        live_client.batch_update([
            {"addSheet": {"properties": {"title": tab_name}}},
            {"deleteSheet": {"sheetId": 987654321}},                    # invalid -> whole batch rejected
        ])
    assert tab_name not in [t["title"] for t in live_client.sheet_properties()]


def test_assumption_writes_outside_the_grid_fail(live_client, tab_name):
    sheet_id = _add_tab(live_client, tab_name, rows=2, cols=2)
    with pytest.raises(SheetsApiError):
        _write(live_client, sheet_id, row=5, col=0, values=["out of bounds"])
    assert tab_props(live_client, tab_name)["gridProperties"] == {"rowCount": 2, "columnCount": 2}


def test_assumption_update_cells_without_rows_clears_fields(live_client, tab_name):
    sheet_id = _add_tab(live_client, tab_name, rows=2, cols=2)
    _write(live_client, sheet_id, row=0, col=0, values=["a", "b"])
    live_client.batch_update([{"updateCells": {"range": {"sheetId": sheet_id}, "fields": "userEnteredValue"}}])
    assert all(cell_kind(c) is None for row in read_grid(live_client, tab_name) for c in row)


def test_assumption_copy_paste_blanks_cells_whose_source_is_empty(live_client, tab_name):
    src = _add_tab(live_client, tab_name + "_src", rows=1, cols=2)
    dst = _add_tab(live_client, tab_name + "_dst", rows=1, cols=2)
    _write(live_client, src, 0, 0, ["new"])                            # B1 of the source stays empty
    _write(live_client, dst, 0, 0, ["old", "stale"])
    rng = lambda sid: {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                       "startColumnIndex": 0, "endColumnIndex": 2}
    live_client.batch_update([{"copyPaste": {"source": rng(src), "destination": rng(dst),
                                             "pasteType": "PASTE_NORMAL"}}])
    row = read_grid(live_client, tab_name + "_dst")[0]
    assert cell_value(row[0]) == "new"
    assert cell_kind(row[1]) is None, "an empty source cell must blank the destination"


def test_assumption_tab_names_clash_case_insensitively(live_client, tab_name):
    _add_tab(live_client, tab_name + "_CASE", rows=1, cols=1)
    with pytest.raises(SheetsApiError):
        _add_tab(live_client, (tab_name + "_CASE").lower(), rows=1, cols=1)


def test_assumption_shrinking_the_grid_deletes_data_outside_it(live_client, tab_name):
    sheet_id = _add_tab(live_client, tab_name, rows=3, cols=3)
    _write(live_client, sheet_id, row=2, col=0, values=["x", "y", "z"])
    live_client.batch_update([{"updateSheetProperties": {
        "properties": {"sheetId": sheet_id, "gridProperties": {"rowCount": 1, "columnCount": 1}},
        "fields": "gridProperties.rowCount,gridProperties.columnCount"}}])
    live_client.batch_update([{"updateSheetProperties": {
        "properties": {"sheetId": sheet_id, "gridProperties": {"rowCount": 3, "columnCount": 3}},
        "fields": "gridProperties.rowCount,gridProperties.columnCount"}}])
    assert all(cell_kind(c) is None for c in read_grid(live_client, tab_name)[2])
