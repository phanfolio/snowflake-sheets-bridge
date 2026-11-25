"""Command line:  snowsheets {check,dry-run,run} <project folder>   (or: python -m snowsheets ...)"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .checks import check_table
from .config import Dataset, Project, load_project
from .errors import PipelineError
from .sheets import SheetsClient, publish
from .snowflake_source import Table, connect, fetch

log = logging.getLogger("snowsheets")
REFRESH_LOG_COLUMNS = ["dataset", "tab", "rows", "columns", "refreshed_at_utc", "code_version"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="snowsheets",
        description="Publish Snowflake query results to a Google Sheet.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    project_help = "project folder, e.g. projects/tpch_sample"

    check = commands.add_parser("check", help="validate the project's .yml and SQL files (no network)")
    check.add_argument("project", type=Path, help=project_help)

    dry = commands.add_parser("dry-run", help="query Snowflake and write CSV previews; never touches Google Sheets")
    dry.add_argument("project", type=Path, help=project_help)
    dry.add_argument("--out", type=Path, help="preview folder (default: previews/<project>)")

    run = commands.add_parser("run", help="query Snowflake and publish to the project's Google Sheet")
    run.add_argument("project", type=Path, help=project_help)

    args = parser.parse_args(argv)
    configure_logging()

    try:
        project = load_project(args.project)
        log.info("Project %s: %d dataset(s) from %s", project.name, len(project.datasets), project.config_file.name)
        if args.command == "check":
            log.info("Config OK")
            return 0
        prepared = query_all(project)
        if args.command == "dry-run":
            write_previews(prepared, args.out or Path("previews") / project.name)
        else:
            publish_project(project, prepared)
        return 0
    except Exception as exc:
        log.error("%s", describe(exc))
        if os.environ.get("VERBOSE_ERRORS") == "1":
            log.exception("Details")
        return 1


def configure_logging() -> None:
    """INFO for snowsheets' own messages; WARNING for every library.

    CI logs in a public repo are public. At INFO, the Snowflake connector logs the account identifier,
    session IDs, result-file URLs and cloud credential lookups, so libraries are held to warnings.
    """
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger("snowsheets").setLevel(logging.INFO)


def query_all(project: Project) -> list[tuple[Dataset, Table]]:
    """Run and check every dataset. Any failure aborts before Google Sheets is touched."""
    prepared: list[tuple[Dataset, Table]] = []
    failed: list[str] = []
    conn = connect()
    try:
        for dataset in project.datasets:
            started = time.monotonic()
            try:
                table = fetch(conn, dataset.sql, dataset.max_rows)
                check_table(dataset, table)
            except Exception as exc:
                failed.append(dataset.name)
                message = describe(exc)               # PipelineError messages already name the dataset
                log.error("%s", message if isinstance(exc, PipelineError) else f"{dataset.name}: {message}")
                if os.environ.get("VERBOSE_ERRORS") == "1":
                    log.exception("Details")
                continue
            prepared.append((dataset, table))
            log.info("%s: %d rows x %d columns (%.1fs)",
                     dataset.name, len(table.rows), len(table.columns), time.monotonic() - started)
    finally:
        conn.close()
    if failed:
        raise PipelineError(f"{len(failed)} dataset(s) failed ({', '.join(failed)}); nothing was published")
    return prepared


def write_previews(prepared: list[tuple[Dataset, Table]], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for dataset, table in prepared:
        path = out / f"{dataset.name}.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(table.columns)
            writer.writerows(["" if v is None else v for v in row] for row in table.rows)
        log.info("%s: preview written to %s", dataset.name, path)
        if dataset.columns is None:
            log.info("%s: to lock this schema, add to the dataset:  columns: [%s]",
                     dataset.name, ", ".join(table.columns))


def publish_project(project: Project, prepared: list[tuple[Dataset, Table]]) -> None:
    spreadsheet_id = os.environ.get("GOOGLE_SHEET_ID", "")
    if not spreadsheet_id:
        raise PipelineError("Missing environment variable GOOGLE_SHEET_ID")

    refreshed_at = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    code_version = (os.environ.get("GITHUB_SHA") or "local")[:7]
    refresh_log = Table(
        columns=REFRESH_LOG_COLUMNS,
        rows=[[d.name, d.tab, len(t.rows), len(t.columns), refreshed_at, code_version] for d, t in prepared],
    )
    tabs = [(dataset.tab, table) for dataset, table in prepared] + [(project.refresh_log_tab, refresh_log)]
    publish(SheetsClient(spreadsheet_id), tabs)
    log.info("Published %d dataset(s) and %s", len(prepared), project.refresh_log_tab)


def describe(exc: BaseException) -> str:
    """Public CI logs: print our own messages in full, otherwise only safe identifiers."""
    if isinstance(exc, PipelineError):
        return str(exc)
    errno, sqlstate = getattr(exc, "errno", None), getattr(exc, "sqlstate", None)
    if errno or sqlstate:
        return f"{type(exc).__name__} (errno={errno}, sqlstate={sqlstate}); set VERBOSE_ERRORS=1 for details"
    return f"{type(exc).__name__}; set VERBOSE_ERRORS=1 for details"
