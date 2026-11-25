# Snowsheets

**A Snowflake → Google Sheets bridge.** Scheduled, all-or-nothing publishing of Snowflake query results to Google Sheets, so Tableau Public dashboards can plug into Snowflake indirectly and stay refreshed, for $0.

## Why it exists

- **Tableau Desktop Free** can connect to Snowflake but can't publish.
- **Tableau Public** can publish but can't connect to Snowflake. It *can* auto-refresh from Google Sheets.
- **Snowsheets** copies Snowflake query results into Google Sheets on a schedule. Tableau Public, or any tool that reads Google Sheets such as Power BI or Looker Studio, then syncs from the Sheet.

```
 Snowflake  ──►  GitHub Actions (daily)  ──►  Google Sheet  ──►  Tableau Public (~24h sync)
 your SQL        snowsheets run                one tab per query      "Keep my data in sync"
```

One repo runs many independent **projects**. A project is one Snowflake account, one Google Sheet and the queries that feed it.

## Design in one minute

| Idea | What it means for you |
|---|---|
| **Shared code, separate projects** | Type handling, validation and publishing live once in the `snowsheets` package. Each project is just a folder of YAML and SQL. |
| **One workflow per project** | Each project has its own schedule, run history, failure emails and **Disable** button. A dead trial account never breaks another project. |
| **One GitHub Environment per project** | Holds that project's Snowflake credentials and Sheet ID. The code always reads the same variable names, and the environment decides the values. |
| **All-or-nothing per project** | Every query runs and is checked first. If any fails, the Sheet is left untouched. If all pass, every tab is swapped in with one atomic Google request. |
| **Real types** | Numbers arrive as numbers and dates as real date cells, so BI tools get proper fields. Values Sheets can't store exactly fail the run instead of being silently rounded. |
| **Schema lock** | Optionally list a dataset's expected columns. If the SQL output changes, the run fails instead of silently breaking downstream fields. |
| **Refresh log tab** | `_refresh_log` records the rows and UTC time of each successful publish, so a dashboard can show "Data as of …". |

## Where to next

- **New here?** Start with the [Quick start](getting-started/quick-start.md).
- **Setting up accounts?** See [Setup](getting-started/setup.md) for Snowflake, Google and GitHub.
- **Something failed?** See [Troubleshooting](guides/troubleshooting.md).
- **How does it work?** Read [Architecture](concepts/architecture.md) and [Type mapping](concepts/type-mapping.md).
- **Every setting**: the [Configuration reference](reference/configuration.md).
