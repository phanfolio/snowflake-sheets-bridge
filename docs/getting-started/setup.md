# Setup

Google setup happens **once per repo**. Snowflake, the Sheet and the GitHub Environment are set up **once per project**.

## Google (once per repo)

One service account publishes to every project's Sheet. GitHub Actions signs in as it without a stored key, using Workload Identity Federation.

```bash
PROJECT_ID=my-gcp-project                                   # a free Google Cloud project
REPO=your-github-user/snowflake-sheets-bridge               # owner/name of this repo
gcloud config set project "$PROJECT_ID"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

gcloud services enable sheets.googleapis.com iamcredentials.googleapis.com sts.googleapis.com

gcloud iam service-accounts create sheets-sync --display-name="Snowflake to Sheets sync"

gcloud iam workload-identity-pools create github \
  --location=global --display-name="GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc github-actions \
  --location=global --workload-identity-pool=github \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository == '${REPO}' && assertion.ref == 'refs/heads/main'"

gcloud iam service-accounts add-iam-policy-binding \
  "sheets-sync@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/${REPO}"
```

Then add two **repository variables** in GitHub → Settings → Secrets and variables → Actions → Variables:

| Variable | Value |
|---|---|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github/providers/github-actions` |
| `GCP_SERVICE_ACCOUNT` | `sheets-sync@<PROJECT_ID>.iam.gserviceaccount.com` |

What the attribute condition does: Google issues tokens only to workflows from **this repo** running on **`main`**. Forks, pull requests and other branches can't publish.

!!! warning "Renaming the repo breaks publishing"
    The condition names the repo by `owner/name`. If you rename or transfer the repo, update the condition.

### Fallback: JSON key

Use this if you'd rather skip federation, or your organization blocks it.

1. Create a JSON key for the service account in the Cloud Console.
2. Store the file's contents as a **repository secret** named `GOOGLE_CREDENTIALS_JSON`.
3. Leave `GCP_WORKLOAD_IDENTITY_PROVIDER` unset. `_sync.yml` picks the key automatically.
4. Delete the local key file.

A JSON key never expires on its own, so rotate it periodically.

## Snowflake (once per project)

Run this in the project's Snowflake account. Adjust the database, schema and object names.

```bash
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -nocrypt -out rsa_key.p8
openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
```

```sql
USE ROLE ACCOUNTADMIN;

CREATE ROLE IF NOT EXISTS SHEETS_SYNC_ROLE;
CREATE WAREHOUSE IF NOT EXISTS SHEETS_SYNC_WH
  WAREHOUSE_SIZE = 'XSMALL' AUTO_SUSPEND = 60 AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE;
GRANT USAGE ON WAREHOUSE SHEETS_SYNC_WH TO ROLE SHEETS_SYNC_ROLE;
GRANT USAGE ON DATABASE analytics TO ROLE SHEETS_SYNC_ROLE;
GRANT USAGE ON SCHEMA analytics.public TO ROLE SHEETS_SYNC_ROLE;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics.public TO ROLE SHEETS_SYNC_ROLE;
GRANT SELECT ON ALL VIEWS IN SCHEMA analytics.public TO ROLE SHEETS_SYNC_ROLE;

-- Reading a database *shared into* your account, such as SNOWFLAKE_SAMPLE_DATA?
-- Shared databases take one grant instead of the USAGE/SELECT grants above:
-- GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE_SAMPLE_DATA TO ROLE SHEETS_SYNC_ROLE;

CREATE USER IF NOT EXISTS SHEETS_SYNC_USER
  TYPE = SERVICE DEFAULT_ROLE = SHEETS_SYNC_ROLE DEFAULT_WAREHOUSE = SHEETS_SYNC_WH;
ALTER USER SHEETS_SYNC_USER SET RSA_PUBLIC_KEY = '<contents of rsa_key.pub without BEGIN/END lines>';
GRANT ROLE SHEETS_SYNC_ROLE TO USER SHEETS_SYNC_USER;

-- Optional but recommended: a hard monthly credit cap
CREATE RESOURCE MONITOR IF NOT EXISTS SHEETS_SYNC_MONITOR
  WITH CREDIT_QUOTA = 5 FREQUENCY = MONTHLY START_TIMESTAMP = IMMEDIATELY
  TRIGGERS ON 100 PERCENT DO SUSPEND;
ALTER WAREHOUSE SHEETS_SYNC_WH SET RESOURCE_MONITOR = SHEETS_SYNC_MONITOR;
```

`TYPE = SERVICE` marks a non-human user: no password, no MFA prompts. Key-pair auth works from any IP, which matters because GitHub's runners don't have fixed addresses.

!!! note "Snowflake isn't free after the trial"
    GitHub, Google and Tableau Public cost nothing, but Snowflake trials end after 30 days. Keep the warehouse XS with `AUTO_SUSPEND = 60`, and keep the resource monitor as a hard cap.

## Google Sheet (once per project)

1. Create a new spreadsheet with your normal Google account. **Use one spreadsheet per project.**
2. **Share** it with the service account email as **Editor**.
3. Copy the ID from the URL: `https://docs.google.com/spreadsheets/d/<ID>/edit`.

The Sheet doesn't need to be public. Tableau Public reads it through your own Google sign-in.

## GitHub Environment (once per project)

1. Go to Settings → Environments → **New environment**, named exactly like the project folder (e.g. `tpch_sample`).
2. Under **Deployment branches and tags**, choose *Selected branches* and add `main`.
3. Add the environment secrets:

| Secret | Value |
|---|---|
| `SNOWFLAKE_ACCOUNT` | `ORGNAME-ACCOUNTNAME` |
| `SNOWFLAKE_USER` | `SHEETS_SYNC_USER` |
| `SNOWFLAKE_PRIVATE_KEY` | full contents of `rsa_key.p8`, including the BEGIN/END lines |
| `SNOWFLAKE_WAREHOUSE` | `SHEETS_SYNC_WH` |
| `SNOWFLAKE_ROLE` | `SHEETS_SYNC_ROLE` |
| `GOOGLE_SHEET_ID` | the spreadsheet ID |
| *optional* `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`, `SNOWFLAKE_PRIVATE_KEY_PASSPHRASE` | |

4. Move `rsa_key.p8` and `rsa_key.pub` out of the repo folder, or delete them. `.gitignore` blocks them, but don't rely on that alone.

## Project files and caller workflow (once per project)

See [Adding a project](../guides/adding-a-project.md) and the [Configuration reference](../reference/configuration.md).

## Tableau Public (once per project)

1. Wait for the first successful run, so the tabs and columns exist.
2. In Tableau Public Desktop, choose Connect → **Google Sheets**, sign in as the Sheet's owner, and pick the tabs.
3. If a date field shows as String, change its type once. See [Type mapping](../concepts/type-mapping.md).
4. Publish with **Keep my data in sync with Google Sheets** ticked.

## Enforce SHA pinning (once per repo)

Every action in `.github/workflows/` is pinned to a full commit SHA ([why](../reference/workflows.md#github-scheduling-caveats)). Turn on enforcement so GitHub refuses any workflow that references an action by tag instead:

```bash
gh api -X PUT repos/<owner>/<repo>/actions/permissions \
  -F enabled=true -f allowed_actions=all -F sha_pinning_required=true
```

It prints nothing on success (HTTP 204, no body). Read it back to confirm:

```bash
gh api repos/<owner>/<repo>/actions/permissions
```

The output should include `"sha_pinning_required": true`. The same switch is in the repo's **Settings → Actions → General**.

!!! note "Repo level, not org level"
    Setting this on the repo affects only this repo. The same setting on an organization applies to **every** repo in it, including existing ones whose workflows use tags. Those would stop running until they're pinned.

## Docs site (once per repo, optional)

The docs you're reading build from `docs/` with MkDocs. To publish them on GitHub Pages, go to Settings → Pages → **Source: GitHub Actions**. The `docs.yml` workflow then deploys on every push to `main` that changes the docs ([Workflows → Docs workflow](../reference/workflows.md#docs-workflow)).
