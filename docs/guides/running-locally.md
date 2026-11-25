# Running locally

Run everything from the repo root. `uv run` uses the project's `.venv`, so you never need to activate it.

## Install

```bash
uv sync          # once, and again after dependency changes
```

## Credentials

Keep a `.env` file outside version control (`.env` is gitignored):

```bash
# .env
SNOWFLAKE_ACCOUNT=ORGNAME-ACCOUNTNAME
SNOWFLAKE_USER=SHEETS_SYNC_USER
SNOWFLAKE_PRIVATE_KEY_PATH=~/.config/snowsheets/snowflake_rsa_key.p8
SNOWFLAKE_WAREHOUSE=SHEETS_SYNC_WH
SNOWFLAKE_ROLE=SHEETS_SYNC_ROLE
GOOGLE_SHEET_ID=...               # only for `run`
GOOGLE_APPLICATION_CREDENTIALS=~/.config/snowsheets/sheets-sync.json   # only for `run`

# At login the Snowflake connector checks whether it's running on a cloud platform, and on a
# laptop it would try your ~/.aws profile. Point the AWS SDK at nothing for this tool:
AWS_SHARED_CREDENTIALS_FILE=/dev/null
AWS_CONFIG_FILE=/dev/null
```

Every variable is listed in [Configuration → Environment variables](../reference/configuration.md#environment-variables).

## Preview without publishing

```bash
uv run --env-file .env snowsheets dry-run projects/tpch_sample
```

`dry-run` runs every query and every check, the same ones `run` uses, then writes CSVs to `previews/tpch_sample/` instead of touching the Sheet. `previews/` is gitignored because it contains real data. Use it to catch errors before they reach a scheduled run.

## Publishing from your machine

A local `run` also needs Google credentials. Keyless federation only works inside GitHub Actions, so use one of:

- **Your login, acting as the service account:**

    ```bash
    gcloud auth application-default login --impersonate-service-account=sheets-sync@<PROJECT_ID>.iam.gserviceaccount.com
    ```

    Your Google user needs the *Service Account Token Creator* role on that account.

- **A key file:** `export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json`.

Usually you don't need a local `run` at all: `dry-run` locally, then **Run workflow** in Actions.
