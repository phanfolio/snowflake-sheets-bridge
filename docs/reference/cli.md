# CLI

```
snowsheets check   <project folder>               validate .yml + SQL files, no network
snowsheets dry-run <project folder> [--out DIR]   query Snowflake, write CSVs, never touch Sheets
snowsheets run     <project folder>               query Snowflake and publish to the Sheet
```

Run these from the repo root as `uv run snowsheets …`, which needs no venv activation. With the venv active, plain `snowsheets …` and `python -m snowsheets …` work too.

| Command | Needs Snowflake creds | Needs Google creds | Writes |
|---|---|---|---|
| `check` | no | no | nothing |
| `dry-run` | yes | no | `previews/<project>/<dataset>.csv` (gitignored: it holds real data) |
| `run` | yes | yes | the project's Google Sheet |

- `dry-run` and `run` apply the same [result checks](configuration.md#checks-on-every-query-result), so `dry-run` shows any error a scheduled run would hit.
- `dry-run` also prints a ready-to-paste `columns: [...]` line for any dataset without a schema lock.
- The exit code is `0` on success and `1` on any failure, which is what makes a GitHub run go red.

## What `run` writes

- One tab per dataset, named by its `tab` key. The tab is resized to exactly the header plus the data rows, typed as described in [Type mapping](../concepts/type-mapping.md).
- The refresh log tab (below).
- Nothing else. Other tabs in the spreadsheet are left alone. The hidden `__staging__*` tabs used during a run are deleted at the end of it.

## The refresh log tab

After every successful publish, the tab named by `refresh_log_tab` (default `_refresh_log`) is rewritten in the same atomic request as the data:

| dataset | tab | rows | columns | refreshed_at_utc | code_version |
|---|---|---|---|---|---|
| daily_sales | daily_sales | 1,234 | 4 | 2026-11-25 08:24:10 | `a1b2c3d` |

- It's the **source of truth** for what is live. It only changes when the data changes.
- `code_version` is the short Git commit that produced the run, or `local`.
- In Tableau, add it as a second data source and show `MAX([refreshed_at_utc])` as "Data as of …".
- When a run fails, this tab keeps its previous contents, so a stale `refreshed_at_utc` means failed runs.
