"""Validate a query result against its dataset's rules before anything is published."""
from __future__ import annotations

from .config import Dataset
from .errors import PipelineError
from .snowflake_source import Table

# Google Sheets stores every number as a 64-bit float, which represents integers exactly only up to 2**53.
MAX_EXACT_INT = 2**53


def check_table(dataset: Dataset, table: Table) -> None:
    if len(set(table.columns)) != len(table.columns):
        raise PipelineError(f"{dataset.name}: query returns duplicate column names; alias them uniquely")

    if dataset.columns is not None and tuple(table.columns) != dataset.columns:
        raise PipelineError(
            f"{dataset.name}: columns changed, which would break downstream fields\n"
            f"    expected: {', '.join(dataset.columns)}\n"
            f"    got:      {', '.join(table.columns)}"
        )

    if not table.rows and dataset.on_empty == "fail":
        raise PipelineError(f"{dataset.name}: query returned 0 rows (set on_empty: allow if that is expected)")

    if len(table.rows) > dataset.max_rows:
        raise PipelineError(
            f"{dataset.name}: query returned more than max_rows={dataset.max_rows:,} rows; "
            "aggregate further or raise max_rows"
        )

    _check_integer_precision(dataset, table)


def _check_integer_precision(dataset: Dataset, table: Table) -> None:
    """Fail instead of letting Sheets silently round large integers (typically IDs).

    The message names the column and data row but never the value: CI logs are public.
    """
    for col, name in enumerate(table.columns):
        for row_number, row in enumerate(table.rows, start=1):
            value = row[col]
            if isinstance(value, int) and not isinstance(value, bool) and abs(value) > MAX_EXACT_INT:
                raise PipelineError(
                    f"{dataset.name}: column {name} has integers too large for Google Sheets to store exactly "
                    f"(first at data row {row_number}; Sheets keeps integers exact only up to ±{MAX_EXACT_INT:,}). "
                    f"Cast the column to text in SQL, e.g. {name}::VARCHAR AS {name}"
                )
