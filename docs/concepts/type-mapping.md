# Type mapping

Snowsheets converts values twice: Snowflake connector value → plain Python value (`normalize`), then Python value → typed Google Sheets cell (`to_cell` plus a per-column number format). The goal is a tab that Tableau, Power BI or any Sheets reader can import as a clean, typed table.

Every row of this table is a test case in `tests/test_bi_contract.py` ([Testing](../development/testing.md)).

| Snowflake | Connector gives | Written to Sheets as | BI tools should see |
|---|---|---|---|
| `NUMBER(p,0)`, `INT` | `int` | number | Number (whole) |
| `NUMBER(p,s)`, `FLOAT` | `Decimal` / `float` | number | Number (decimal) |
| NaN / ±Inf | `float` | empty cell | null |
| `VARCHAR` | `str` | text (`stringValue`, never parsed as a formula) | String |
| `VARCHAR` empty string `''` | `str` | **empty cell**, the same as NULL | null |
| `BOOLEAN` | `bool` | boolean | Boolean |
| `DATE` | `date` | serial number + `yyyy-mm-dd` format | Date |
| `TIMESTAMP_NTZ` | `datetime` | serial number + `yyyy-mm-dd hh:mm:ss` | Date & Time |
| `TIMESTAMP_LTZ` / `_TZ` | aware `datetime` | **converted to UTC**, then as above | Date & Time (UTC) |
| `TIME` | `time` | day fraction + `hh:mm:ss` | Time-formatted number |
| `BINARY` | `bytes` | hex text | String |
| `VARIANT` / `OBJECT` / `ARRAY` | JSON `str` | text | String |
| `NULL` | `None` | empty cell | null |

## What every published tab guarantees

These are the rules a BI connector relies on, checked by `assert_bi_ready()` in the tests:

- Row 1 is the header: unique, non-empty text in query order, with no number format.
- The grid is exactly the header plus the data rows. There are no stray rows or columns that would import as blank fields.
- Each column holds one value type and one number format.
- There are no formulas, only values. Text such as `=SUM(A1)` stays text.
- Nothing from a previous publish is left behind, including old number formats.

## Dates and times

Sheets stores dates as **serial numbers**: days since 1899-12-30, with the time of day as a fraction (`46023.5` = 2026-01-01 12:00). Formats are applied to whole columns in the swap request, and a column's type comes from its first non-null value.

Timestamps with a time zone are converted to UTC, because Sheets cells have no time zone.

!!! note "Unverified in the real tools"
    The "BI tools should see" column is what these cell types and formats *should* produce. It hasn't been checked against a live Tableau Public or Power BI connection. If a field arrives as String, change its type once in the tool.

## Precision

Sheets stores **every number as a 64-bit float**. Integers are exact only up to **±9,007,199,254,740,992** (2⁵³, 16 digits). Beyond that they're silently rounded:

| Sent | Stored by Sheets |
|---|---|
| `9007199254740992` (2⁵³) | `9007199254740992` ✓ |
| `9007199254740993` | `9007199254740992` ✗ |
| `98765432109876543` | `98765432109876544` ✗ |
| `12345678901234567890` | `12345678901234567168` ✗ |

**Integers:** a run fails if any value is outside ±2⁵³, naming the column and the first data row:

```
orders: column ORDER_ID has integers too large for Google Sheets to store exactly (first at data row 17; …).
Cast the column to text in SQL, e.g. ORDER_ID::VARCHAR AS ORDER_ID
```

`NUMBER(38,0)` (Snowflake's default integer type) means *up to* 38 digits, not that every value has 38. The check looks at **actual values**, so ordinary counts and most IDs pass. Large IDs are identifiers rather than quantities anyway, so text is the right type for them in a dashboard.

**Decimals:** non-integer `NUMBER(p,s)` values become floats, which keep about 15–17 significant digits. That isn't checked, since it's normal for analytics. If you need every digit, cast to `VARCHAR` in SQL.

## Long text

Text longer than 50,000 characters, the Sheets per-cell limit, is truncated.
