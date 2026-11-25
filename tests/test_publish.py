"""Staging -> atomic swap: what reaches the Sheet, and what happens when something fails."""
from __future__ import annotations

from datetime import date

import pytest

from fakes import FakeSheets, assert_bi_ready, cell_value
from snowsheets import sheets
from snowsheets.config import STAGING_PREFIX
from snowsheets.errors import PipelineError
from snowsheets.sheets import SheetsApiError, publish
from snowsheets.snowflake_source import Table

DATA = Table(["ORDER_DATE", "REVENUE"], [[date(2026, 1, 1), 10], [date(2026, 1, 2), 20.5]])
LOG = Table(["dataset", "rows"], [["daily_sales", 2]])


def staging_tabs(fake: FakeSheets) -> list[str]:
    return [t for t in fake.titles() if t.startswith(STAGING_PREFIX)]


def test_publishes_every_tab_and_leaves_no_staging(fake_sheets):
    publish(fake_sheets, [("daily_sales", DATA), ("_refresh_log", LOG)])
    assert staging_tabs(fake_sheets) == []
    assert_bi_ready(fake_sheets.read_grid("daily_sales"), DATA.columns, n_rows=2)
    assert_bi_ready(fake_sheets.read_grid("_refresh_log"), LOG.columns, n_rows=1)


def test_staging_tabs_are_hidden_and_exactly_sized(fake_sheets):
    publish(fake_sheets, [("daily_sales", DATA)])
    added = [r["addSheet"]["properties"] for r in fake_sheets.calls[0] if "addSheet" in r]
    staging = next(p for p in added if p["title"] == STAGING_PREFIX + "daily_sales")
    assert staging["hidden"] is True
    assert staging["gridProperties"] == {"rowCount": 3, "columnCount": 2}


def test_all_tabs_swap_in_one_request(fake_sheets):
    publish(fake_sheets, [("daily_sales", DATA), ("_refresh_log", LOG)])
    commit = fake_sheets.calls[-1]
    assert sum("copyPaste" in r for r in commit) == 2
    assert sum("deleteSheet" in r for r in commit) == 2


def test_existing_tab_is_matched_case_insensitively(fake_sheets):
    fake_sheets._addSheet({"properties": {"title": "Daily_Sales"}})
    publish(fake_sheets, [("daily_sales", DATA)])
    assert [t for t in fake_sheets.titles() if t.casefold() == "daily_sales"] == ["Daily_Sales"]
    assert cell_value(fake_sheets.read_grid("Daily_Sales")[2][1]) == 20.5


def test_leftover_staging_from_a_crashed_run_is_removed_first(fake_sheets):
    fake_sheets._addSheet({"properties": {"title": STAGING_PREFIX + "old", "hidden": True}})
    publish(fake_sheets, [("daily_sales", DATA)])
    assert "deleteSheet" in fake_sheets.calls[0][0]
    assert staging_tabs(fake_sheets) == []


@pytest.mark.parametrize("failing_step", ["copyPaste", "updateCells"])
def test_failure_leaves_targets_untouched_and_cleans_staging(failing_step):
    fake = FakeSheets()
    publish(fake, [("daily_sales", DATA)])                 # yesterday's data
    before = fake.read_grid("daily_sales")

    fake.fail_when = lambda reqs: any(failing_step in r for r in reqs)
    with pytest.raises(SheetsApiError):
        publish(fake, [("daily_sales", Table(["X"], [[1]] * 7))])

    assert fake.read_grid("daily_sales") == before
    assert staging_tabs(fake) == []


def test_cell_limit_is_checked_before_anything_is_created(fake_sheets):
    huge = Table(["a"], [None] * 6_000_000)                # only its length is used before the check
    with pytest.raises(PipelineError, match="10,000,000-cell"):
        publish(fake_sheets, [("big", huge)])
    assert fake_sheets.calls == []


def test_large_tables_are_written_in_contiguous_chunks(fake_sheets, monkeypatch):
    monkeypatch.setattr(sheets, "MAX_REQUEST_BYTES", 500)
    rows = [[i, f"row {i}", date(2026, 1, 1)] for i in range(60)]
    publish(fake_sheets, [("t", Table(["N", "LABEL", "D"], rows))])

    writes = [r[0]["updateCells"] for r in fake_sheets.calls if "updateCells" in r[0] and "rows" in r[0]["updateCells"]]
    assert len(writes) > 1
    starts = [w["start"]["rowIndex"] for w in writes]
    assert starts[0] == 0
    assert all(s + len(w["rows"]) == nxt for s, w, nxt in zip(starts, writes, starts[1:]))

    grid = fake_sheets.read_grid("t")
    assert_bi_ready(grid, ["N", "LABEL", "D"], n_rows=60)
    assert [cell_value(row[0]) for row in grid[1:]] == list(range(60))
