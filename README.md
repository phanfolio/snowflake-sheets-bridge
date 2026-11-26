# Snowsheets

[![Docs](https://img.shields.io/badge/docs-phanfolio.github.io-blue?logo=materialformkdocs&logoColor=white)](https://phanfolio.github.io/snowflake-sheets-bridge/)

**A Snowflake → Google Sheets bridge.** Scheduled, all-or-nothing publishing of
Snowflake query results to Google Sheets, so Tableau Public dashboards can plug into Snowflake indirectly and stay refreshed, for $0.

- **Tableau Desktop Free** can connect to Snowflake but can't publish.
- **Tableau Public** can publish but can't connect to Snowflake. It can auto-refresh from Google Sheets.
- **This repo** copies Snowflake query results into Google Sheets on a schedule. Tableau Public then syncs from the Sheet about every 24 hours.

```
 Snowflake  ──►  GitHub Actions (daily)  ──►  Google Sheet  ──►  Tableau Public (~24h sync)
 your SQL        snowsheets run                one tab per query      "Keep my data in sync"
```

One repo can run many independent **projects**. A project is one Snowflake account, one Google Sheet and the queries that feed it.

---

## Design in one minute

| Idea | What it means for you |
|---|---|
| **Shared code, separate projects** | Type handling, validation and publishing live once in `snowsheets/`. Each project is just a folder of YAML and SQL. |
| **One workflow per project** | Each project has its own schedule, run history, failure emails and **Disable** button. A dead trial account never breaks another project. |
| **One GitHub Environment per project** | Holds that project's Snowflake credentials and Sheet ID. The code always reads the same variable names, and the environment decides the values. |
| **All-or-nothing per project** | Every query runs and is checked first. If any fails, the Sheet is left untouched. If all pass, every tab is swapped in with one atomic Google request. |
| **Real types** | Numbers arrive as numbers and dates as real date cells, so Tableau gets proper fields. |
| **Schema lock** | Optionally list a dataset's expected columns. If the SQL output changes, the run fails instead of silently breaking your Tableau fields. |
| **Refresh log tab** | `_refresh_log` records the rows and UTC time of each successful publish, so a dashboard can show "Data as of …". |

Deeper detail: [Architecture](docs/concepts/architecture.md) and [Type mapping](docs/concepts/type-mapping.md).

## Repo layout

```
.github/workflows/
  _sync.yml            shared job (don't run directly)
  sync-tpch_sample.yml caller for the "tpch_sample" project: schedule + project name
  tests.yml            runs the test suite on pull requests and pushes to main
  docs.yml             builds the docs site and deploys it to GitHub Pages
snowsheets/            shared Python package
tests/                 pytest suite; Snowflake and Google are faked, so no secrets needed
defaults.yml           repo-wide defaults
projects/
  tpch_sample/         working example on Snowflake's built-in sample data
    tpch_sample.yml    the project's config (any name; must be the only .yml in the folder)
    queries/*.sql
docs/                  docs site source (MkDocs → GitHub Pages)
mkdocs.yml             docs site config and navigation
pyproject.toml         package metadata, dependencies, the `snowsheets` command
uv.lock                exact dependency versions CI installs (created by `uv lock`)
.python-version        Python version uv uses
```

---

## Quick start

### Once per repo

0. **Tooling.** Install [uv](https://docs.astral.sh/uv/), run `uv lock` in the repo root, and commit the resulting `uv.lock`. CI installs exactly those versions.
1. **Google service account.** Create one in Google Cloud, enable the Sheets API, and set up keyless sign-in from GitHub. Follow [Setup → Google](docs/getting-started/setup.md#google-once-per-repo).
2. **Repo variables.** In GitHub → Settings → Secrets and variables → Actions → *Variables*, add `GCP_WORKLOAD_IDENTITY_PROVIDER` and `GCP_SERVICE_ACCOUNT`.

### Once per project

Using a project called `marketing` as the example:

1. **Snowflake.** Create a read-only service user with a key pair in that account ([SQL here](docs/getting-started/setup.md#snowflake-once-per-project)).
2. **Google Sheet.** Create a new spreadsheet and **share** it with the service account's email as **Editor**.
3. **Project folder.** Create `projects/marketing/marketing.yml` and `projects/marketing/queries/*.sql`. Copy `projects/tpch_sample/` as a starting point.
4. **Caller workflow.** Copy `.github/workflows/sync-tpch_sample.yml` to `sync-marketing.yml` and replace every `tpch_sample` with `marketing`. Use a different cron minute.
5. **Environment.** In GitHub → Settings → Environments, create `marketing` and limit it to the `main` branch. Add these secrets:
   `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PRIVATE_KEY`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_ROLE`, `GOOGLE_SHEET_ID`.
6. **First run.** Push, then in Actions → *Sync: marketing* → **Run workflow**. Check the Sheet.
7. **Tableau Public.** Connect Tableau Public Desktop to the Sheet with the **Google Drive** connector, and publish with **Keep my data in sync…** ticked ([details](docs/getting-started/setup.md#tableau-public-once-per-project)).

The folder name, the environment name and the `project:` value in the caller must all be the same.

### Try a project locally first

```bash
uv sync                                          # creates .venv with the locked dependencies
uv run pytest                                    # runs the test suite, no network
uv run snowsheets check projects/marketing       # validates YAML + SQL, no network
uv run snowsheets dry-run projects/marketing     # queries Snowflake, writes CSVs to previews/, never touches Sheets
```

Local environment variables: [Running locally](docs/guides/running-locally.md).

### Retiring a project (e.g. a trial account expired)

In Actions → *Sync: <project>* → **⋯ → Disable workflow**. To remove it for good, delete its caller workflow, its `projects/<name>/` folder and its environment.

---

## Trade-offs of this approach

| | Upside | Downside |
|---|---|---|
| **GitHub Actions as the scheduler** | Free and unlimited on a public repo; logs and history built in | Cron can start 10–30 min late. Scheduled workflows are **paused after 60 days with no commits** to the repo |
| **Google Sheets as the bridge** | The only cloud source Tableau Public auto-refreshes from | 10M cells per spreadsheet; slows down long before that. Aggregate in SQL |
| **One workflow per project** | Failures, schedules and credentials are isolated; disable one with a click | A caller file per project, and the folder, environment and `project:` names must match by hand |
| **Shared code** | Fix or improve once and every project gets it | A bad change to `snowsheets/` re-runs and affects every project. Shared-code pushes trigger all callers |
| **All-or-nothing per project** | Tabs in one Sheet never disagree; failures keep yesterday's data | One broken query holds back the whole project's refresh |
| **Staging + atomic swap** | Works for any data size without exposing half-written tabs | Needs up to ~2× the cells while staging, and more API calls than a direct write |
| **Keyless Google auth** | No long-lived Google key stored anywhere | Around 10 setup commands; only works from this repo's `main` branch (use a key file locally) |
| **Snowflake key-pair** | No password or MFA; works from any IP | Still a long-lived secret per project; rotate it yourself |
| **Public repo** | Unlimited Actions minutes; showcases your work | SQL, config and logs are public. Logs print counts only, never data |
| **Tableau Public** | Free hosting and sharing | Anyone can download the data behind a dashboard. Publish only non-sensitive, aggregated data |
| **"$0"** | GitHub, Google and Tableau Public cost nothing | **Snowflake does.** Trials end after 30 days. Use an XS warehouse with `AUTO_SUSPEND = 60` and a resource monitor |

## Docs

The full docs are a site built from `docs/` and published on GitHub Pages (Settings → Pages → Source: GitHub Actions). Preview locally with `uv run --only-group docs mkdocs serve`.

- **Getting started:** [Quick start](docs/getting-started/quick-start.md) · [Setup](docs/getting-started/setup.md)
- **Guides:** [Adding a project](docs/guides/adding-a-project.md) · [Running locally](docs/guides/running-locally.md) · [Troubleshooting](docs/guides/troubleshooting.md)
- **Concepts:** [Architecture](docs/concepts/architecture.md) · [Type mapping](docs/concepts/type-mapping.md)
- **Reference:** [Configuration](docs/reference/configuration.md) · [CLI](docs/reference/cli.md) · [Workflows](docs/reference/workflows.md)
- **Development:** [Testing](docs/development/testing.md)
