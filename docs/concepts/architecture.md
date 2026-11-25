# Architecture

## Components

| Module | Responsibility |
|---|---|
| `snowsheets/config.py` | Find the project's `.yml`, merge `defaults.yml`, validate everything |
| `snowsheets/snowflake_source.py` | Key-pair connection, run a query, normalise values to plain Python types |
| `snowsheets/checks.py` | Per-dataset rules: schema lock, `on_empty`, `max_rows`, duplicate columns, integer precision |
| `snowsheets/sheets.py` | Sheets API client (pacing and retries), value-to-cell conversion, staged atomic publish |
| `snowsheets/cli.py` | `check` / `dry-run` / `run` commands, the refresh log table, log-safe error messages |

The only network dependencies are the Snowflake connector and two Sheets REST endpoints: reading the tab list (`GET spreadsheets/{id}`) and `POST spreadsheets/{id}:batchUpdate`.

## A run, step by step

```
check ─► query all datasets ─► validate all ─► stage ─► atomic swap
          (Snowflake)            │               │         │
                                 └─ any failure: └─ failure: staging deleted,
                                    stop; Sheet     Sheet untouched
                                    untouched
```

1. **Load config.** Invalid config fails before any network call. The workflow runs `check` as its own step for this reason.
2. **Query every dataset** in one Snowflake session, in config order. A failing dataset is logged and the rest still run, so one run reports every problem at once.
3. **Validate every result** ([checks](../reference/configuration.md#checks-on-every-query-result)). If any dataset failed in step 2 or 3, the run stops here and nothing is written.
4. **Prepare the Sheet.** Delete any `__staging__*` tabs a crashed earlier run left behind, then check the cell budget.
5. **Stage.** Create one hidden `__staging__<tab>` per target tab, sized exactly, and fill it in chunks of about 1.5 MB. Readers only use the real tabs, so nothing visible has changed yet.
6. **Swap.** Send one `batchUpdate` that, for each tab, resizes the target, clears it, copies the staging tab over it with `copyPaste`, and applies date and time formats. The same request then rewrites the refresh log tab the same way and deletes every staging tab.

Google applies a `batchUpdate` **entirely or not at all**, so after step 6 either every tab shows the new data or none does. The swap request is small whatever the data size, because the copy happens on Google's side.

### Why staging instead of one big write?

A single request holding every row would also be all-or-nothing, but request size is limited, and you don't know your data size up front. Staging separates *moving the data*, which can take many requests, from *switching to it*, which is always one request.

## Failure behaviour

| What fails | Effect on the Sheet | Run result |
|---|---|---|
| Invalid YAML or a missing SQL file | none | fails at **Validate config** |
| Snowflake login | none | fails |
| Any dataset's query or check | none; **all datasets held back** | fails, listing every failed dataset |
| Sheets error while staging | none; staging tabs deleted (best effort) | fails |
| Swap request rejected | none; the request is atomic | fails |
| Process killed mid-run | none; leftover staging tabs are removed by the next run | fails / times out |

Projects are isolated: each runs in its own workflow and job, with its own credentials and its own spreadsheet.

!!! warning "One spreadsheet per project"
    Every run deletes leftover `__staging__*` tabs. Two projects sharing a spreadsheet could delete each other's staging tabs mid-run.

**Edge case:** if the swap actually succeeded but the response was lost to a 5xx error, the retry fails because the staging tabs are already gone. The run then reports failure even though the data is published. The refresh log tab shows what really happened.

## Logging policy (public repo)

Workflow logs in a public repo are public, so:

- Row data is **never** logged. The logs show row and column counts, timings, dataset and column names, and row numbers.
- The pipeline's own errors (`PipelineError`) print in full. They mention column names, which are in the public config anyway.
- Libraries such as the Snowflake connector and Google auth only log warnings. At INFO the connector logs the account identifier, session IDs and cloud credential lookups.
- Other exceptions print only their type plus the Snowflake `errno`/`sqlstate`. Set `VERBOSE_ERRORS=1` for one run to see full tracebacks, then turn it off.

## Limits and quotas

| Limit | Value | How it's handled |
|---|---|---|
| Cells per spreadsheet | 10,000,000, **allocated** grid across all tabs | Tabs are sized exactly. The run fails before writing if the peak, including staging, would exceed the limit, and warns at 80% |
| Characters per cell | 50,000 | Truncated |
| Exact integers | ±2⁵³ | The run fails; see [Type mapping → Precision](type-mapping.md#precision) |
| Request size | ~2 MB recommended | Staging chunks of ≤ 1.5 MB |
| Sheets write quota | ~60 requests/min/user | ≥ 1.1 s between writes; exponential backoff on 429/5xx (5 → 80 s, 6 attempts) |
| Snowflake statement | 600 s | `STATEMENT_TIMEOUT_IN_SECONDS` |
| GitHub job | 30 min (set in `_sync.yml`; GitHub's cap is 6 h) | Raise `timeout-minutes` if needed |
| Practical size | Sheets and BI syncs slow down well before 10M cells | Aggregate in SQL. `max_rows` defaults to 100k |
