"""Unit tests for the two conversion steps: Snowflake value -> Python value -> Sheets cell."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from snowsheets.sheets import column_kinds, kind_of, to_cell, to_serial
from snowsheets.snowflake_source import MAX_CELL_CHARS, Table, normalize


# ---------------------------------------------------------------- normalize (Snowflake -> Python)
@pytest.mark.parametrize("raw, expected", [
    (None, None),
    (True, True),
    (7, 7),
    (Decimal("5.00"), 5),
    (Decimal("1.25"), 1.25),
    (Decimal("-0"), 0),
    (1.5, 1.5),
    ("abc", "abc"),
    (b"\x01\xff", "01ff"),
    (bytearray(b"\x0a"), "0a"),
    (date(2026, 1, 1), date(2026, 1, 1)),
    (datetime(2026, 1, 1, 12), datetime(2026, 1, 1, 12)),
])
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_integral_decimal_becomes_int_not_float():
    assert type(normalize(Decimal("5.00"))) is int


@pytest.mark.parametrize("raw", [float("nan"), float("inf"), Decimal("NaN"), Decimal("-Infinity")])
def test_non_finite_numbers_become_null(raw):
    assert normalize(raw) is None


def test_aware_timestamps_convert_to_naive_utc():
    aware = datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=-6)))
    assert normalize(aware) == datetime(2026, 1, 1, 18)
    assert normalize(aware).tzinfo is None


def test_time_drops_timezone():
    assert normalize(time(9, tzinfo=timezone.utc)).tzinfo is None


def test_long_text_and_unknown_types_are_bounded_strings():
    assert normalize("x" * (MAX_CELL_CHARS + 10)) == "x" * MAX_CELL_CHARS
    assert normalize(["a", 1]) == "['a', 1]"


# ---------------------------------------------------------------- Sheets serial numbers
@pytest.mark.parametrize("value, serial", [
    (date(1899, 12, 30), 0.0),
    (date(1899, 12, 31), 1.0),
    (date(1900, 3, 1), 61.0),          # Sheets has no fake 1900-02-29 (unlike Excel's 1900 date system)
    (date(2026, 1, 1), 46023.0),
    (datetime(2026, 1, 1, 12), 46023.5),
    (datetime(2026, 1, 1, 0, 0, 0, 500_000), 46023 + 0.5 / 86_400),
    (time(6), 0.25),
    (time(0), 0.0),
])
def test_to_serial(value, serial):
    assert to_serial(value) == pytest.approx(serial, abs=1e-9)


# ---------------------------------------------------------------- Sheets cells
@pytest.mark.parametrize("value, cell", [
    (None, {}),
    (True, {"userEnteredValue": {"boolValue": True}}),
    (3, {"userEnteredValue": {"numberValue": 3}}),
    (2.5, {"userEnteredValue": {"numberValue": 2.5}}),
    ("=1+1", {"userEnteredValue": {"stringValue": "=1+1"}}),      # never a formula
    ("", {}),                                                     # Sheets can't store "" apart from NULL
    (date(2026, 1, 1), {"userEnteredValue": {"numberValue": 46023.0}}),
])
def test_to_cell(value, cell):
    assert to_cell(value) == cell


def test_bool_is_not_treated_as_a_number():
    assert kind_of(True) == "bool"
    assert to_cell(False) == {"userEnteredValue": {"boolValue": False}}


def test_every_normalized_value_serializes_to_strict_json():
    samples = [None, True, 1, 1.5, "x", b"\x00", date(2026, 1, 1), datetime(2026, 1, 1, 1), time(1),
               Decimal("2.50"), float("nan"), Decimal("Infinity")]
    json.dumps([to_cell(normalize(v)) for v in samples], allow_nan=False)


def test_column_kind_comes_from_first_non_null_value():
    table = Table(["d", "n", "s", "empty"], [[None, 1, "x", None], [date(2026, 1, 1), 2.5, "y", None]])
    assert column_kinds(table) == ["date", "number", "text", "text"]


def test_datetime_is_not_mistaken_for_date():
    assert kind_of(datetime(2026, 1, 1)) == "datetime"
    assert kind_of(date(2026, 1, 1)) == "date"
