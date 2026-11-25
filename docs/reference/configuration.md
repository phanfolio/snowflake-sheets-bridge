# Configuration

Snowsheets reads two kinds of YAML file and a set of environment variables.

| File | Scope | Required |
|---|---|---|
| `defaults.yml` (repo root) | Defaults shared by every project | No; built-in values apply if it's missing |
| `projects/<name>/<anything>.yml` | One project's datasets and overrides | Yes |

## How a project's config file is found

Point the CLI at a project **folder**, for example `uv run snowsheets run projects/tpch_sample`. The config is the **single `.yml` or `.yaml` file at the root of that folder**:

- The file name doesn't matter. `tpch_sample.yml` is the convention; `project.yml` works the same.
- Zero or several YAML files at the folder root is an error. YAML files in subfolders such as `queries/` are ignored.
- The **project name** is the folder name, used in logs and preview paths. It must match the GitHub Environment and the caller's `project:` input ([Workflows](workflows.md#why-the-names-must-match)).

## Precedence

Settings resolve in this order, later winning:

```
built-in  <  defaults.yml  <  project .yml (top level)  <  dataset entry
```

`refresh_log_tab` is project-wide, so a dataset entry can't override it. `on_empty` and `max_rows` can be set at every level.

## defaults.yml

It's found by looking in each folder above the project folder, stopping at the repo root (the folder with `pyproject.toml`). In this layout that is always the repo root. Because the search starts from the project folder, not from where the package is installed, it works whether `snowsheets` is installed editable (`uv sync`) or as a regular wheel.

| Key | Type | Built-in | Meaning |
|---|---|---|---|
| `refresh_log_tab` | string | `_refresh_log` | Name of the tab that records each successful publish ([details](cli.md#the-refresh-log-tab)) |
| `on_empty` | `fail` \| `allow` | `fail` | What to do when a query returns 0 rows |
| `max_rows` | positive integer | `100000` | Maximum rows a dataset may return |

No other keys are allowed.

## Project .yml

```yaml
refresh_log_tab: _refresh_log   # optional override
on_empty: fail                  # optional override, applies to every dataset below
max_rows: 100000                # optional override

datasets:                       # required, non-empty list
  - name: daily_sales
    sql: queries/daily_sales.sql
    tab: daily_sales
    columns: [ORDER_DATE, REGION, REVENUE, ORDERS]
    on_empty: fail
    max_rows: 50000
```

### Top-level keys

| Key | Required | Meaning |
|---|---|---|
| `datasets` | **yes** | List of dataset entries (below) |
| `refresh_log_tab`, `on_empty`, `max_rows` | no | Override `defaults.yml` for this project |

### Dataset keys

| Key | Required | Type | Default | Meaning |
|---|---|---|---|---|
| `name` | **yes** | string | | Identifier used in logs, previews (`<name>.csv`) and the refresh log. Letters, digits, `_`, `-`; must start with a letter or digit. Unique within the project. |
| `sql` | **yes** | path | | `.sql` file, **relative to the project `.yml`**. Exactly one statement. |
| `tab` | no | string | `name` | Google Sheet tab to overwrite. Created if missing. |
| `columns` | no | list of strings | none (no lock) | **Schema lock.** The query's output columns must match exactly, same names in the same order, or the run fails. |
| `on_empty` | no | `fail` \| `allow` | inherited | `fail`: 0 rows fails the project's run. `allow`: publish a header-only tab. |
| `max_rows` | no | positive integer | inherited | More rows than this fails the run. Only `max_rows + 1` rows are fetched, so a runaway query can't exhaust memory. |

### Validation rules

The `check` command enforces all of these, with no network access:

- Unknown keys at any level are errors, so typos such as `colums:` fail loudly.
- Dataset names must be unique.
- Tab names must be unique **case-insensitively**, and must differ from `refresh_log_tab` (Google Sheets treats `Sales` and `sales` as the same tab).
- Tab names are 1–80 characters with no leading or trailing spaces. They must not start with the reserved prefix `__staging__`.
- Each `sql` file must exist and must not be empty.

### Column names

Snowflake upper-cases unquoted identifiers: `SELECT order_date` returns `ORDER_DATE`. These names become your dashboard field names, so give every expression an alias. To keep lower case, quote the alias: `AS "order_date"`. `dry-run` prints the exact `columns:` line for any dataset that doesn't have one yet.

## Checks on every query result

`dry-run` and `run` apply these after each query. Any failure stops the project's run before anything is written.

| Check | Fails when | Fix |
|---|---|---|
| Unique columns | Two output columns share a name | Alias them uniquely |
| Schema lock | `columns:` is set and the output differs | Update `columns:` and the dashboard, or revert the SQL |
| Empty result | 0 rows and `on_empty: fail` | Fix upstream data, or `on_empty: allow` |
| Row limit | More than `max_rows` rows | Aggregate further, or raise `max_rows` |
| Integer precision | Any integer outside ±2⁵³ | Cast the column to `VARCHAR` ([why](../concepts/type-mapping.md#precision)) |

## Environment variables

### Snowflake (per project; GitHub Environment secrets)

| Variable | Required | Meaning |
|---|---|---|
| `SNOWFLAKE_ACCOUNT` | yes | Account identifier, `ORGNAME-ACCOUNTNAME` |
| `SNOWFLAKE_USER` | yes | Service user name |
| `SNOWFLAKE_PRIVATE_KEY` | yes\* | PEM private key text, including the `BEGIN`/`END` lines. Literal `\n` sequences are accepted. |
| `SNOWFLAKE_PRIVATE_KEY_PATH` | yes\* | Path to the PEM file instead, convenient locally |
| `SNOWFLAKE_PRIVATE_KEY_PASSPHRASE` | no | Only if the key is encrypted |
| `SNOWFLAKE_WAREHOUSE` | yes | Warehouse to run queries on |
| `SNOWFLAKE_ROLE` | yes | Role to use |
| `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA` | no | Session defaults. Without them, fully qualify table names in SQL. |

\* Provide one of `SNOWFLAKE_PRIVATE_KEY` or `SNOWFLAKE_PRIVATE_KEY_PATH`. The text form wins if both are set.

### Google (per project and per repo)

| Variable | Where | Meaning |
|---|---|---|
| `GOOGLE_SHEET_ID` | Environment secret (per project) | Spreadsheet ID from its URL: `docs.google.com/spreadsheets/d/<ID>/edit` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Set automatically in Actions; optional locally | Path to a credentials file. Snowsheets uses Google's Application Default Credentials. |

### Behaviour switches

| Variable | Effect |
|---|---|
| `VERBOSE_ERRORS=1` | Print full tracebacks. Off by default because logs in a public repo are public. |

## GitHub settings

| Name | Kind | Level | Required | Purpose |
|---|---|---|---|---|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Variable | Repository | for keyless | Full provider resource name ([Setup](../getting-started/setup.md#google-once-per-repo)) |
| `GCP_SERVICE_ACCOUNT` | Variable | Repository | for keyless | Service account email |
| `GOOGLE_CREDENTIALS_JSON` | Secret | Repository | fallback only | Service account JSON key. Used only when `GCP_WORKLOAD_IDENTITY_PROVIDER` is unset. |
| Environment `<project>` | Environment | Per project | yes | Holds the Snowflake secrets and `GOOGLE_SHEET_ID`. Restrict it to the `main` branch. |
