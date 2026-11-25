# Workflows

| File | Role |
|---|---|
| `.github/workflows/_sync.yml` | The shared sync job. Triggered by `workflow_call` only, never on its own. Takes one input, `project`. |
| `.github/workflows/sync-<project>.yml` | A short **caller** per project: when to run (schedule, manual, push) and which project. |
| `.github/workflows/tests.yml` | Runs the test suite on pull requests and pushes to `main`. |
| `.github/workflows/docs.yml` | Builds this docs site and deploys it to GitHub Pages. |

## Shared workflow + one caller per project

Each caller is a separate workflow, so each project gets:

- its own run history and failure emails,
- its own schedule,
- its own **Disable workflow** button,
- its own runner. Projects run in parallel and can't slow each other down or hit each other's job limits.

## What `_sync.yml` does

1. Selects the GitHub Environment named after `inputs.project`, which supplies that project's secrets.
2. Uses a concurrency group `sync-<project>`. A second run of the same project waits for the first instead of overlapping. Different projects never wait on each other.
3. Checks out the code and installs the exact locked dependencies, without dev tools, using `uv sync --locked --no-dev`. `--locked` fails the run if `uv.lock` is out of date with `pyproject.toml`.
4. Runs `uv run snowsheets check projects/<project>`.
5. Signs in to Google with keyless federation when `GCP_WORKLOAD_IDENTITY_PROVIDER` is set, otherwise with the `GOOGLE_CREDENTIALS_JSON` key.
6. Runs `uv run snowsheets run projects/<project>` with the environment's secrets.

### Why the names must match

`project: tpch_sample` in the caller selects all three of:

- the folder `projects/tpch_sample/`,
- the GitHub Environment `tpch_sample`,
- the concurrency group `sync-tpch_sample`.

A mismatch usually shows up as "Project folder not found" or "Missing environment variable SNOWFLAKE_ACCOUNT", the second meaning the environment wasn't found.

### Secrets flow

The caller passes `secrets: inherit`, so repository-level secrets such as `GOOGLE_CREDENTIALS_JSON` reach `_sync.yml`. Environment secrets are read directly by `_sync.yml`'s job because it declares `environment:`. Every project uses the **same secret names**, and the environment decides their values.

### Permissions

Callers grant `contents: read` and `id-token: write`, and `_sync.yml` asks for the same. A called workflow can never have more permissions than its caller. `id-token: write` lets the job request the short-lived token Google exchanges for access.

## Triggers (in each caller)

| Trigger | When |
|---|---|
| `schedule` | Daily, in **UTC**. Give each project a different minute; GitHub delays jobs most at the top of the hour. |
| `workflow_dispatch` | The **Run workflow** button in Actions |
| `push` to `main` | When this project's folder, the shared code (`snowsheets/`, `defaults.yml`, `pyproject.toml`, `uv.lock`, `.python-version`, `_sync.yml`) or the caller itself changes. With `main` protected, that push is the merge of a pull request |

Because shared-code paths are in every caller, **merging a change to `snowsheets/` re-publishes every project**. That's intentional: you see immediately if the change broke anything. Remove those paths from a caller if you'd rather a project only refresh on its own schedule.

## Tests workflow

`tests.yml` runs `uv run pytest` on every pull request and every push to `main`. It needs no environment or secrets, so pull requests from forks run it safely.

It's independent of the sync workflows: a failing test never blocks a scheduled refresh.

## Branch protection on main

`main` is protected so that untested code can't reach it, and therefore can't reach every project's Sheet:

| Rule | Setting |
|---|---|
| Changes arrive by pull request | required, with 0 approvals (a solo maintainer can merge their own) |
| Required check | **pytest**, from the Tests workflow |
| Branch must be up to date with `main` before merging | yes |
| Applies to admins | yes: nobody pushes to `main` directly |
| Force pushes and branch deletion | blocked |

Only `pytest` is required. The Docs build runs only when docs change, and a required check that never runs would block every other pull request. Docs pull requests still show the Docs build, and a broken build is visible on the pull request.

Day to day:

```bash
git switch -c my-change
# edit, commit
git push -u origin my-change
gh pr create --fill          # Tests runs on the pull request
gh pr merge --squash         # allowed once pytest passes; the merge triggers the sync callers
```

Dependabot's pull requests follow the same rule: they merge once `pytest` passes on them. To change the rules, go to Settings → Branches → `main`.

## Docs workflow

`docs.yml` builds this site with `mkdocs build --strict`, which fails on broken links or anchors.

- On **pull requests** that touch `docs/` or `mkdocs.yml`, it only builds, so broken docs show up as a failed check.
- On **pushes to `main`**, and on manual runs, it also deploys to GitHub Pages.

One-time setup: Settings → Pages → **Source: GitHub Actions**.

## GitHub scheduling caveats

- **60-day pause:** in public repos, GitHub disables scheduled workflows after 60 days without repository activity. This hits **all** projects at once. Any commit resets the clock, and disabled workflows can be re-enabled in the Actions tab.
- **Delays:** scheduled runs can start 10–30 minutes late, and are occasionally dropped under heavy load.
- **Default branch only:** schedules run on the default branch, which must be `main` for the keyless auth condition to match.
- **Actions are pinned to commit SHAs.** Every `uses:` points at a full 40-character commit, with the release it came from as a comment (`actions/checkout@3d3c42e…  # v7.0.1`). A tag such as `v7` can be moved to different code later; a commit can't. `.github/dependabot.yml` opens a weekly pull request that updates the SHAs and comments together.
