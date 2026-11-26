"""The conversion contract: Snowflake value -> Google Sheets cell -> a table Tableau / Power BI can import.

Each test runs real snowsheets code end to end (normalize -> publish) against FakeSheets, then reads
the tab back the way a BI connector does: row 1 is the header, every other row is data, each column
holds one value type and one number format.

Not covered (needs the real tools): how Tableau and Power BI themselves infer types from these cells.
What *is* covered is that the Sheet hands them unambiguous, typed, rectangular input.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from fakes import assert_bi_ready, cell_kind, cell_value, number_format
from snowsheets.sheets import publish
from snowsheets.snowflake_source import Table, normalize

CST = timezone(timedelta(hours=-6))

# One row per Snowflake type. Mirrors the type-mapping table in docs/architecture.md.
TYPE_MATRIX = [
    #            value the connector returns       cell value        kind      number format
    pytest.param(42,                                42,              "number", None,        id="NUMBER(38,0)"),
    pytest.param(Decimal("12.50"),                  12.5,            "number", None,        id="NUMBER(10,2)"),
    pytest.param(Decimal("7.00"),                   7,               "number", None,        id="NUMBER(10,2)-integral"),
    pytest.param(3.25,                              3.25,            "number", None,        id="FLOAT"),
    pytest.param(-0.5,                              -0.5,            "number", None,        id="FLOAT-negative"),
    pytest.param("north",                           "north",         "string", None,        id="VARCHAR"),
    pytest.param("=SUM(A1:A9)",                     "=SUM(A1:A9)",   "string", None,        id="VARCHAR-formula-lookalike"),
    pytest.param("00123",                           "00123",         "string", None,        id="VARCHAR-leading-zeros"),
    pytest.param("",                                None,            None,     None,        id="VARCHAR-empty-string-is-null"),
    pytest.param(True,                              True,            "bool",   None,        id="BOOLEAN"),
    pytest.param(date(2026, 1, 1),                  46023,           "number", "DATE",      id="DATE"),
    pytest.param(datetime(2026, 1, 1, 6),           46023.25,        "number", "DATE_TIME", id="TIMESTAMP_NTZ"),
    pytest.param(datetime(2026, 1, 1, tzinfo=CST),  46023.25,        "number", "DATE_TIME", id="TIMESTAMP_TZ-as-UTC"),
    pytest.param(time(18),                          0.75,            "number", "TIME",      id="TIME"),
    pytest.param(b"\x00\xff",                       "00ff",          "string", None,        id="BINARY"),
    pytest.param('{"a": 1}',                        '{"a": 1}',      "string", None,        id="VARIANT"),
]


@pytest.mark.parametrize("raw, expected, kind, fmt", TYPE_MATRIX)
def test_each_snowflake_type_lands_as_a_typed_cell(fake_sheets, raw, expected, kind, fmt):
    table = Table(columns=["VALUE"], rows=[[normalize(raw)], [normalize(None)]])
    publish(fake_sheets, [("t", table)])

    grid = fake_sheets.read_grid("t")
    assert_bi_ready(grid, ["VALUE"], n_rows=2)
    value_cell, null_cell = grid[1][0], grid[2][0]
    assert cell_value(value_cell) == expected
    assert cell_kind(value_cell) == kind
    assert number_format(value_cell) == fmt
    assert cell_kind(null_cell) is None, "NULL becomes an empty cell, not 'None' or 0"


@pytest.mark.parametrize("raw", [float("nan"), float("inf"), float("-inf"), Decimal("NaN"), Decimal("Infinity")])
def test_non_finite_numbers_become_empty_cells(fake_sheets, raw):
    # FakeSheets also rejects NaN/Infinity in request JSON, as Google does.
    publish(fake_sheets, [("t", Table(["X"], [[normalize(raw)]]))])
    assert cell_kind(fake_sheets.read_grid("t")[1][0]) is None


def test_text_is_truncated_to_the_sheets_cell_limit(fake_sheets):
    publish(fake_sheets, [("t", Table(["X"], [[normalize("x" * 60_000)]]))])
    assert len(cell_value(fake_sheets.read_grid("t")[1][0])) == 50_000


def test_sub_second_values_never_round_across_midnight(fake_sheets):
    # Found live in Tableau Public: 2000-02-29 23:59:59.999999 was read as Null, because the stored
    # day fraction rounds up to the next day. Whole-second truncation keeps it on the same day.
    near_midnight = normalize(datetime(2000, 2, 29, 23, 59, 59, 999_999))
    publish(fake_sheets, [("t", Table(["TS"], [[near_midnight]]))])

    value = cell_value(fake_sheets.read_grid("t")[1][0])
    assert value == pytest.approx(36585 + 86_399 / 86_400, abs=1e-12)
    assert int(value) == 36585, "still on 2000-02-29"


def test_realistic_table_is_bi_ready(fake_sheets):
    header = ["ORDER_DATE", "REGION", "REVENUE", "ORDERS", "IS_PROMO", "UPDATED_AT", "NOTE"]
    raw_rows = [
        (date(2026, 1, 1), "north", Decimal("1200.50"), 14, True,  datetime(2026, 1, 2, 3, tzinfo=CST), None),
        (date(2026, 1, 1), "south", Decimal("980.00"),  9,  False, datetime(2026, 1, 2, 4, tzinfo=CST), "promo"),
        (date(2026, 1, 2), None,    None,               0,  None,  None,                               None),
    ]
    table = Table(header, [[normalize(v) for v in row] for row in raw_rows])
    publish(fake_sheets, [("daily_sales", table)])

    grid = fake_sheets.read_grid("daily_sales")
    assert_bi_ready(grid, header, n_rows=3)
    assert [number_format(grid[1][c]) for c in range(len(header))] == \
        ["DATE", None, None, None, None, "DATE_TIME", None]
    assert cell_value(grid[1][5]) == pytest.approx(46024 + 9 / 24), "03:00 CST stored as 09:00 UTC"
    assert not fake_sheets.props("daily_sales")["hidden"]


def test_republishing_leaves_no_stale_cells_or_formats(fake_sheets):
    publish(fake_sheets, [("t", Table(["A", "B", "C"], [[date(2026, 1, 1), "x", 1]] * 5))])
    publish(fake_sheets, [("t", Table(["A", "B"], [["now text", 2]]))])

    grid = fake_sheets.read_grid("t")
    assert_bi_ready(grid, ["A", "B"], n_rows=1)
    assert number_format(grid[1][0]) is None, "yesterday's DATE format on column A is gone"


def test_existing_hand_made_tab_is_fully_replaced(fake_sheets):
    fake_sheets._addSheet({"properties": {"title": "t", "gridProperties": {"rowCount": 50, "columnCount": 10}}})
    fake_sheets.seed("t", [["junk"] * 10] * 50)
    publish(fake_sheets, [("t", Table(["A"], [[1]]))])
    assert_bi_ready(fake_sheets.read_grid("t"), ["A"], n_rows=1)


def test_empty_result_publishes_a_header_only_table(fake_sheets):
    publish(fake_sheets, [("t", Table(["A", "B"], []))])
    assert_bi_ready(fake_sheets.read_grid("t"), ["A", "B"], n_rows=0)


def test_all_null_column_stays_empty_and_unformatted(fake_sheets):
    publish(fake_sheets, [("t", Table(["A", "B"], [[1, None], [2, None]]))])
    grid = fake_sheets.read_grid("t")
    assert_bi_ready(grid, ["A", "B"], n_rows=2)
    assert all(row[1] == {} for row in grid[1:])
