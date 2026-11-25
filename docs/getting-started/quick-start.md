# Quick start

The short path from an empty repo to a refreshing dashboard. Each step links to the details.

## Once per repo

1. **Tooling.** Install [uv](https://docs.astral.sh/uv/), run `uv lock` in the repo root, and commit `uv.lock`. CI installs exactly those versions.
2. **Google service account.** Create one in Google Cloud, enable the Sheets API, and set up keyless sign-in from GitHub ([Setup → Google](setup.md#google-once-per-repo)).
3. **Repo variables.** In GitHub → Settings → Secrets and variables → Actions → *Variables*, add `GCP_WORKLOAD_IDENTITY_PROVIDER` and `GCP_SERVICE_ACCOUNT`.

## Once per project

Using a project called `marketing` as the example:

1. **Snowflake.** Create a read-only service user with a key pair in that account ([SQL](setup.md#snowflake-once-per-project)).
2. **Google Sheet.** Create a new spreadsheet and **share** it with the service account's email as **Editor**.
3. **Project folder.** Create `projects/marketing/marketing.yml` and `projects/marketing/queries/*.sql`. Copy `projects/tpch_sample/` as a starting point ([Configuration](../reference/configuration.md)).
4. **Caller workflow.** Copy `.github/workflows/sync-tpch_sample.yml` to `sync-marketing.yml` and replace every `tpch_sample` with `marketing`. Use a different cron minute.
5. **Environment.** In GitHub → Settings → Environments, create `marketing` and limit it to the `main` branch. Add the secrets `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PRIVATE_KEY`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_ROLE` and `GOOGLE_SHEET_ID`.
6. **First run.** Push, then in Actions → *Sync: marketing* → **Run workflow**. Check the Sheet.
7. **Tableau Public.** Connect Tableau Public Desktop to the Sheet and publish with **Keep my data in sync with Google Sheets** ticked.

!!! warning "Names must match"
    The folder name, the GitHub Environment name and the `project:` value in the caller must all be the same. See [Workflows → Why the names must match](../reference/workflows.md#why-the-names-must-match).

The full walkthrough is in [Adding a project](../guides/adding-a-project.md).

## Try it locally first

```bash
uv sync                                          # creates .venv with the locked dependencies
uv run pytest                                    # runs the test suite, no network
uv run snowsheets check projects/marketing       # validates YAML + SQL, no network
uv run snowsheets dry-run projects/marketing     # queries Snowflake, writes CSVs, never touches Sheets
```

Local credentials: [Running locally](../guides/running-locally.md).
