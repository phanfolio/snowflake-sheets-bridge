# Testing

```bash
uv run pytest            # whole suite, under a second, no network
uv run pytest -k bi      # just the conversion-contract tests
```

Snowflake and Google are never contacted. The suite runs in CI on every pull request ([Tests workflow](../reference/workflows.md#tests-workflow)).

## What's covered

| File | Covers |
|---|---|
| `test_bi_contract.py` | **The conversion contract.** Every Snowflake type → a typed Sheets cell → a tab Tableau / Power BI can import: header in row 1, unique names, one type and one number format per column, no stray rows, columns or formulas, nothing stale left after republishing |
| `test_values.py` | `normalize()` and value → cell conversion, date serial numbers, strict JSON |
| `test_checks.py` | Schema lock, `on_empty`, `max_rows`, duplicate columns, integer precision |
| `test_publish.py` | Staging → atomic swap, case-insensitive tab matching, cleanup and untouched targets on failure, cell budget, chunked writes |
| `test_sheets_client.py` | HTTP retries, giving up, Google error messages |
| `test_snowflake_source.py` | Private key formats and passphrases, connection settings, `max_rows + 1` fetching |
| `test_config.py` | Config discovery, precedence, every validation error, and that `projects/tpch_sample` is valid |
| `test_cli.py` | `check` / `dry-run` / `run` end to end, all-or-nothing on failure, the refresh log, log-safe errors |

## FakeSheets: what it is and how far to trust it

`tests/fakes.py` contains `FakeSheets`, a **hand-written, in-memory model of the Google Sheets API**. It isn't a Google library: Google publishes no official Sheets emulator. It applies the same `batchUpdate` requests the real API receives, so tests can read the finished tab back the way a BI connector would.

It is deliberately strict. Every rule it models has been **checked against the real Google Sheets API** by the [live tests](#live-tests-against-a-real-sheet):

| Rule | Verified live |
|---|---|
| A `batchUpdate` is all-or-nothing | ✓ |
| Writes outside a tab's grid fail rather than expanding it | ✓ |
| `updateCells` with no `rows` clears the named fields | ✓ |
| `copyPaste` (`PASTE_NORMAL`) blanks destination cells whose source is empty | ✓ |
| Tab names clash case-insensitively | ✓ |
| Shrinking a tab's grid deletes the data outside it | ✓ |
| An empty string `""` is stored as an empty cell, the same as NULL | ✓, found by the live tests; the fake originally got this wrong |
| At most 10M cells per spreadsheet, 50,000 characters per cell; no NaN/Infinity in JSON | Google's documented limits and the JSON standard |

Error message wording in the fake is approximate.

## Live tests against a real Sheet

`tests/live/` runs the real `SheetsClient` and `publish()` against a real spreadsheet, reads the result back from Google (values *and* number formats), and checks it with the same `assert_bi_ready()` contract. It also tests each rule in the table above directly.

They're **opt-in**: skipped unless both variables are set, so CI never needs Google credentials.

```bash
GOOGLE_APPLICATION_CREDENTIALS=~/.config/snowsheets/sheets-sync.json \
SNOWSHEETS_LIVE_SHEET_ID=<scratch spreadsheet ID> \
uv run pytest -m live -v
```

- Use a **scratch spreadsheet** shared with the service account as Editor. The tests create, overwrite and delete tabs, all prefixed `live_`, and remove them at the end.
- A run takes about a minute, because writes are paced to stay inside Google's quota.
- Run them after changing `snowsheets/sheets.py`, and whenever you suspect Google's behaviour has changed.

## Not covered

- Real Snowflake is **verified manually, not automated**: `projects/tpch_sample` runs against Snowflake's built-in sample data (see [Running locally](../guides/running-locally.md)), and its published tabs were read back from Google and matched row for row.
- GitHub Actions keyless auth.
- How Tableau or Power BI themselves infer types from the cells.
- The workflow YAML.

## Writing tests

- Shared fixtures are in `tests/conftest.py`: `repo` (a temp repo with `pyproject.toml` and `defaults.yml`), `make_project` (writes a project folder) and `fake_sheets`.
- `assert_bi_ready(grid, header, n_rows)` in `tests/fakes.py` checks a published tab against the BI contract. Use it in any test that publishes.
- Tests outside `tests/live/` must not need network access or credentials. The `_clean_env` fixture removes credential variables from the environment for every test.
