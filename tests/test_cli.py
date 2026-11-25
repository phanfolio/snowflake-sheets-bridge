"""End-to-end CLI runs with Snowflake and Google faked: check, dry-run, run, and all-or-nothing."""
from __future__ import annotations

import csv
import logging
from datetime import date

import pytest

from fakes import FakeSheets, assert_bi_ready, cell_value, number_format
from snowsheets import cli
from snowsheets.snowflake_source import Table

TWO_DATASETS = """
datasets:
  - name: daily_sales
    sql: queries/daily_sales.sql
    columns: [ORDER_DATE, REVENUE]
  - name: regions
    sql: queries/regions.sql
"""
SQL = {"daily_sales.sql": "select * from sales", "regions.sql": "select * from regions"}


@pytest.fixture
def project(make_project):
    return make_project("sales", yml=TWO_DATASETS, sql=SQL)


@pytest.fixture
def snowflake(monkeypatch):
    """Fake Snowflake: results keyed by SQL text. Set a value to an Exception to make that query fail."""
    results = {
        "select * from sales": Table(["ORDER_DATE", "REVENUE"], [[date(2026, 1, 1), 10], [date(2026, 1, 2), 12.5]]),
        "select * from regions": Table(["REGION"], [["north"], ["south"]]),
    }

    class Connection:
        closed = False

        def close(self):
            Connection.closed = True

    def fake_fetch(conn, sql, max_rows):
        result = results[sql]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(cli, "connect", Connection)
    monkeypatch.setattr(cli, "fetch", fake_fetch)
    results["connection"] = Connection
    return results


@pytest.fixture
def sheet(monkeypatch):
    fake = FakeSheets()
    monkeypatch.setattr(cli, "SheetsClient", lambda spreadsheet_id: fake)
    monkeypatch.setenv("GOOGLE_SHEET_ID", "sheet123")
    return fake


def test_check_exit_codes(project, repo):
    assert cli.main(["check", str(project)]) == 0
    assert cli.main(["check", str(repo / "projects" / "nope")]) == 1


def test_dry_run_writes_previews_and_suggests_a_schema_lock(project, snowflake, tmp_path, caplog):
    out = tmp_path / "previews"
    with caplog.at_level(logging.INFO):
        assert cli.main(["dry-run", str(project), "--out", str(out)]) == 0
    with (out / "daily_sales.csv").open() as handle:
        assert list(csv.reader(handle)) == [["ORDER_DATE", "REVENUE"], ["2026-01-01", "10"], ["2026-01-02", "12.5"]]
    assert "columns: [REGION]" in caplog.text            # regions has no lock yet


def test_run_publishes_every_dataset_and_the_refresh_log(project, snowflake, sheet, monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "abcdef1234567")
    assert cli.main(["run", str(project)]) == 0

    assert_bi_ready(sheet.read_grid("daily_sales"), ["ORDER_DATE", "REVENUE"], n_rows=2)
    assert_bi_ready(sheet.read_grid("regions"), ["REGION"], n_rows=2)

    log_grid = sheet.read_grid("_refresh_log")
    assert_bi_ready(log_grid, cli.REFRESH_LOG_COLUMNS, n_rows=2)
    first = [cell_value(c) for c in log_grid[1]]
    assert first[:4] == ["daily_sales", "daily_sales", 2, 2]
    assert first[5] == "abcdef1"
    assert number_format(log_grid[1][4]) == "DATE_TIME"
    assert snowflake["connection"].closed


def test_one_failing_dataset_means_nothing_is_published(project, snowflake, sheet):
    snowflake["select * from regions"] = RuntimeError("boom")
    assert cli.main(["run", str(project)]) == 1
    assert sheet.calls == []                               # the Sheet was never touched
    assert snowflake["connection"].closed


def test_schema_drift_means_nothing_is_published(project, snowflake, sheet, caplog):
    snowflake["select * from sales"] = Table(["ORDER_DATE", "AMOUNT"], [[date(2026, 1, 1), 10]])
    assert cli.main(["run", str(project)]) == 1
    assert sheet.calls == []
    assert "columns changed" in caplog.text


def test_oversized_integer_means_nothing_is_published(project, snowflake, sheet, caplog):
    snowflake["select * from regions"] = Table(["REGION"], [[12345678901234567890]])
    assert cli.main(["run", str(project)]) == 1
    assert sheet.calls == []
    assert "regions: column REGION has integers too large" in caplog.text
    assert "12345678901234567890" not in caplog.text


def test_dry_run_reports_the_same_errors_before_publishing(project, snowflake, tmp_path, caplog):
    snowflake["select * from regions"] = Table(["REGION"], [[2**60]])
    assert cli.main(["dry-run", str(project), "--out", str(tmp_path)]) == 1
    assert "integers too large" in caplog.text


def test_run_requires_a_sheet_id(project, snowflake, monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    assert cli.main(["run", str(project)]) == 1


def test_unexpected_errors_never_print_their_message():
    # Messages of non-pipeline errors may contain data, and CI logs are public.
    assert cli.describe(RuntimeError("customer 4411 owes 30")) == "RuntimeError; set VERBOSE_ERRORS=1 for details"


def test_snowflake_errors_show_only_their_codes():
    error = Exception("SQL compilation error: secret_table")
    error.errno, error.sqlstate = 2003, "42S02"
    assert cli.describe(error) == "Exception (errno=2003, sqlstate=42S02); set VERBOSE_ERRORS=1 for details"


def test_library_logs_are_limited_to_warnings(project):
    # At INFO the Snowflake connector logs the account identifier, session IDs and credential
    # lookups; CI logs are public, so only snowsheets' own messages may print at INFO.
    assert cli.main(["check", str(project)]) == 0
    assert logging.getLogger("snowsheets").isEnabledFor(logging.INFO)
    assert logging.getLogger("snowsheets.sheets").isEnabledFor(logging.INFO)
    assert not logging.getLogger("snowflake.connector").isEnabledFor(logging.INFO)
    assert not logging.getLogger("google.auth").isEnabledFor(logging.INFO)
