"""Per-dataset rules applied to a query result before anything is published."""
from __future__ import annotations

from pathlib import Path

import pytest

from snowsheets.checks import check_table
from snowsheets.config import Dataset
from snowsheets.errors import PipelineError
from snowsheets.snowflake_source import Table


def dataset(**overrides) -> Dataset:
    values = dict(name="ds", sql_path=Path("q.sql"), sql="select 1", tab="ds",
                  columns=None, on_empty="fail", max_rows=10)
    values.update(overrides)
    return Dataset(**values)


def test_valid_result_passes():
    check_table(dataset(columns=("A",)), Table(["A"], [[1]]))


def test_schema_lock_catches_renamed_or_reordered_columns():
    with pytest.raises(PipelineError, match="columns changed") as info:
        check_table(dataset(columns=("A", "B")), Table(["B", "A"], [[1, 2]]))
    assert "expected: A, B" in str(info.value) and "got:      B, A" in str(info.value)


def test_empty_result_fails_by_default_and_passes_when_allowed():
    with pytest.raises(PipelineError, match="0 rows"):
        check_table(dataset(), Table(["A"], []))
    check_table(dataset(on_empty="allow"), Table(["A"], []))


def test_more_than_max_rows_fails():
    with pytest.raises(PipelineError, match="max_rows=10"):
        check_table(dataset(), Table(["A"], [[1]] * 11))
    check_table(dataset(), Table(["A"], [[1]] * 10))


def test_duplicate_column_names_fail():
    with pytest.raises(PipelineError, match="duplicate column names"):
        check_table(dataset(), Table(["A", "A"], [[1, 2]]))


@pytest.mark.parametrize("value", [2**53, -(2**53), 9_007_199_254_740_991, 0, True, 1.5e300])
def test_integers_sheets_can_store_exactly_pass(value):
    check_table(dataset(), Table(["ID"], [[value]]))


@pytest.mark.parametrize("value", [2**53 + 1, -(2**53) - 1, 12345678901234567890,
                                   12345678901234567890123456789012345678])
def test_integers_sheets_would_round_fail(value):
    with pytest.raises(PipelineError, match="column ORDER_ID has integers too large") as info:
        check_table(dataset(), Table(["REGION", "ORDER_ID"], [["north", 1], ["south", value]]))
    message = str(info.value)
    assert "first at data row 2" in message
    assert "ORDER_ID::VARCHAR AS ORDER_ID" in message
    assert str(value) not in message, "the value itself must never reach public logs"
