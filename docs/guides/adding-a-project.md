# Adding a project

A project is one Snowflake account, one Google Sheet and the queries that feed it. Adding one never touches the others.

## Steps

1. **Project folder.** Create `projects/<project>/<project>.yml` and `projects/<project>/queries/`. Copying `projects/tpch_sample/` is the quickest start. Every key is in the [Configuration reference](../reference/configuration.md).
2. **Caller workflow.** Copy `.github/workflows/sync-tpch_sample.yml` to `sync-<project>.yml`. Replace `tpch_sample` in the `name:`, both `paths:` entries and `project:`, and change the cron minute.
3. **Snowflake.** Create the service user, role, warehouse and key pair in that project's account ([Setup → Snowflake](../getting-started/setup.md#snowflake-once-per-project)).
4. **Google Sheet.** Create a spreadsheet for this project only and share it with the service account as **Editor** ([Setup → Google Sheet](../getting-started/setup.md#google-sheet-once-per-project)).
5. **GitHub Environment.** Create the environment `<project>` with its secrets, limited to `main` ([Setup → GitHub Environment](../getting-started/setup.md#github-environment-once-per-project)).
6. **Validate locally:**

    ```bash
    uv run snowsheets check projects/<project>
    uv run --env-file .env snowsheets dry-run projects/<project>
    ```

7. **Push.** The push trigger runs the project once. Check the run in Actions and the tabs in the Sheet.
8. **Lock the schema.** `dry-run` prints a `columns: [...]` line for each dataset without one. Paste it into the project `.yml` so a changed query fails the run instead of breaking dashboard fields.

!!! warning "Names must match"
    The folder, the GitHub Environment and the caller's `project:` value must be identical. See [Why the names must match](../reference/workflows.md#why-the-names-must-match).

## Disabling or retiring a project

- **Pause**, e.g. a trial account expired and you might come back: Actions → *Sync: &lt;project&gt;* → **⋯** → **Disable workflow**. The config and secrets stay, and you re-enable it the same way.
- **Remove:** delete `sync-<project>.yml`, `projects/<project>/` and the `<project>` environment. The Sheet and dashboard keep their last data.
