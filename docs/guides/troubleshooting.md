# Troubleshooting

## Where errors show up

| Where | What you see |
|---|---|
| **GitHub Actions run** | Actions → *Sync: &lt;project&gt;* → the red ✗ run → job **sync &lt;project&gt;**. Config errors are in the **Validate config** step; everything else is in the **Publish** step, on lines marked `ERROR`. |
| **Email** | GitHub emails you when a run fails. For scheduled runs it goes to whoever last changed the workflow's cron line. |
| **Your terminal** | `uv run --env-file .env snowsheets dry-run projects/<project>` runs the same queries and checks and prints the same errors, without publishing anything. |
| **The Sheet** | Nothing changes, because a failed run never writes. The `_refresh_log` tab's `refreshed_at_utc` stops advancing, which is how a dashboard's "Data as of" label shows a problem. |

Every failed run exits with code `1`. Data checks fail **before** anything is written, so the Sheet always keeps the last good data.

A failing run's log looks like this:

```
2026-11-26 08:24:03 INFO Project sales: 2 dataset(s) from sales.yml
2026-11-26 08:24:05 INFO daily_sales: 1234 rows x 4 columns (1.2s)
2026-11-26 08:24:06 ERROR orders: column ORDER_ID has integers too large for Google Sheets to store exactly (first at data row 17; Sheets keeps integers exact only up to ±9,007,199,254,740,992). Cast the column to text in SQL, e.g. ORDER_ID::VARCHAR AS ORDER_ID
2026-11-26 08:24:06 ERROR 1 dataset(s) failed (orders); nothing was published
```

Messages name datasets, columns and row numbers but **never values**, because logs in a public repo are public.

## Error reference

| Message | Likely cause → fix |
|---|---|
| `Project folder not found` | The caller's `project:` doesn't match the folder name |
| `expected exactly one .yml file at the project root` | An extra `.yml` was added next to the project config; move it |
| `unknown key(s) ...` | A typo in a YAML key; the message lists the allowed keys |
| `Missing environment variable SNOWFLAKE_...` | The environment name doesn't match the project, or the secret isn't set in that environment |
| `Snowflake private key could not be loaded` | The secret is missing its BEGIN/END lines, or the key is encrypted without a passphrase |
| `DatabaseError (errno=250001 ...)` | Snowflake login failed: wrong account identifier, user or public key, or the trial expired. Re-run with `VERBOSE_ERRORS=1` |
| `ProgrammingError (errno=2003 ...)` | An object doesn't exist or the role lacks a grant |
| `columns changed, which would break downstream fields` | The SQL output changed. Update `columns:` **and** the dashboard, or revert the SQL |
| `query returned 0 rows` | An upstream table is empty, or a filter is wrong. Use `on_empty: allow` if it's expected |
| `more than max_rows` | The query isn't aggregated enough, or raise `max_rows` |
| `integers too large for Google Sheets to store exactly` | A column holds integers above ±2⁵³, usually IDs. Cast it to text in SQL, as the message shows. See [Type mapping → Precision](../concepts/type-mapping.md#precision) |
| `duplicate column names` | Two expressions produce the same column name; give each a unique alias |
| `Sheets API HTTP 403 PERMISSION_DENIED` | The Sheet isn't shared with the service account, or the Sheets API isn't enabled |
| `Sheets API HTTP 404 NOT_FOUND` | Wrong `GOOGLE_SHEET_ID` |
| `google-github-actions/auth` step fails | The attribute condition doesn't match (repo renamed, or run from a branch other than `main`), or the provider/SA variables are wrong |
| `over Google Sheets' 10,000,000-cell limit` | Too much data in one spreadsheet. Aggregate, lower `max_rows`, or split into two projects |
| `uv sync --locked` fails | `uv.lock` is missing or out of date: run `uv lock` and commit it |

## Getting more detail

For anything else, re-run once with `VERBOSE_ERRORS=1` set as a repository or environment variable, and read the traceback.

!!! warning
    The log is public. Turn `VERBOSE_ERRORS` off again afterwards, because tracebacks can include data.
