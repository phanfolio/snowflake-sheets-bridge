"""Google Sheets side: stage every table in hidden tabs, then swap them all in with one atomic request.

Phase 1  create hidden __staging__<tab> sheets (and any target tab that doesn't exist yet)
Phase 2  fill staging sheets in as many chunked requests as needed   <- readers see no change
Phase 3  one batchUpdate: resize + clear + copy staging over each target, set number formats,
         delete staging. Google applies a batchUpdate entirely or not at all.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime
from datetime import time as dtime
from typing import Iterable

import google.auth
import requests
from google.auth.transport.requests import AuthorizedSession

from .config import STAGING_PREFIX
from .errors import PipelineError
from .snowflake_source import Table, Value

log = logging.getLogger(__name__)

API_ROOT = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
CELL_LIMIT = 10_000_000             # per spreadsheet, all tabs, counted on allocated grid size
CELL_WARN_RATIO = 0.8
MAX_REQUEST_BYTES = 1_500_000       # Google recommends keeping requests under ~2 MB
MIN_SECONDS_BETWEEN_WRITES = 1.1    # stays under 60 write requests/min/user
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 6

_SERIAL_EPOCH = datetime(1899, 12, 30)   # day 0 of Sheets' date serial numbers
NUMBER_FORMATS = {
    "date": {"type": "DATE", "pattern": "yyyy-mm-dd"},
    "datetime": {"type": "DATE_TIME", "pattern": "yyyy-mm-dd hh:mm:ss"},
    "time": {"type": "TIME", "pattern": "hh:mm:ss"},
}


class SheetsApiError(PipelineError):
    """A Sheets API error. Google's messages describe the request, not the cell contents."""


# --------------------------------------------------------------------------- HTTP client
class SheetsClient:
    """Minimal client for the two endpoints the pipeline needs, with pacing and retries."""

    def __init__(self, spreadsheet_id: str) -> None:
        # Application Default Credentials: keyless federation in GitHub Actions, or a key file /
        # gcloud login locally. See docs/setup.md.
        credentials, _ = google.auth.default(scopes=SCOPES)
        self._session = AuthorizedSession(credentials)
        self._url = f"{API_ROOT}/{spreadsheet_id}"
        self._last_write = 0.0

    def sheet_properties(self) -> list[dict]:
        body = self._request("GET", self._url, params={"fields": "sheets.properties"})
        return [sheet["properties"] for sheet in body.get("sheets", [])]

    def batch_update(self, reqs: list[dict]) -> list[dict]:
        if not reqs:
            return []
        wait = MIN_SECONDS_BETWEEN_WRITES - (time.monotonic() - self._last_write)
        if wait > 0:
            time.sleep(wait)
        try:
            body = self._request("POST", f"{self._url}:batchUpdate", json={"requests": reqs})
        finally:
            self._last_write = time.monotonic()
        return body.get("replies", [])

    def _request(self, method: str, url: str, **kwargs) -> dict:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = self._session.request(method, url, timeout=120, **kwargs)
            except requests.RequestException as exc:
                if attempt == MAX_ATTEMPTS:
                    raise SheetsApiError(f"Sheets API unreachable ({type(exc).__name__})") from exc
                problem = type(exc).__name__
            else:
                if resp.ok:
                    return resp.json()
                if resp.status_code not in RETRYABLE_STATUS or attempt == MAX_ATTEMPTS:
                    raise SheetsApiError(_describe(resp))
                problem = f"HTTP {resp.status_code}"
            delay = 5 * 2 ** (attempt - 1)        # 5, 10, 20, 40, 80 s: the per-minute quota refills
            log.warning("Sheets API %s; retrying in %ss", problem, delay)
            time.sleep(delay)
        raise AssertionError("unreachable")


def _describe(resp: requests.Response) -> str:
    try:
        error = resp.json().get("error", {})
        status, message = error.get("status", ""), str(error.get("message", ""))[:300]
    except ValueError:
        status, message = "", ""
    return f"Sheets API HTTP {resp.status_code} {status}: {message}".rstrip(": ")


# --------------------------------------------------------------------------- value -> cell
def kind_of(value: Value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, dtime):
        return "time"
    return "text"


def column_kinds(table: Table) -> list[str]:
    """A column's kind is the kind of its first non-null value (Snowflake columns are single-typed)."""
    kinds = ["text"] * len(table.columns)
    for col in range(len(kinds)):
        for row in table.rows:
            kind = kind_of(row[col])
            if kind:
                kinds[col] = kind
                break
    return kinds


def to_serial(value: date | datetime | dtime) -> float:
    """Sheets stores dates as days since 1899-12-30 and times as a fraction of a day."""
    if isinstance(value, datetime):
        return (value - _SERIAL_EPOCH).total_seconds() / 86_400
    if isinstance(value, date):
        return float((value - _SERIAL_EPOCH.date()).days)
    seconds = value.hour * 3600 + value.minute * 60 + value.second + value.microsecond / 1e6
    return seconds / 86_400


def to_cell(value: Value) -> dict:
    if value is None:
        return {}
    if isinstance(value, bool):
        return {"userEnteredValue": {"boolValue": value}}
    if isinstance(value, (int, float)):
        return {"userEnteredValue": {"numberValue": value}}
    if isinstance(value, (date, dtime)):           # covers datetime too; formatted per column later
        return {"userEnteredValue": {"numberValue": to_serial(value)}}
    text = str(value)
    if text == "":                                  # Google stores "" as an empty cell, i.e. the same as NULL
        return {}
    return {"userEnteredValue": {"stringValue": text}}         # stringValue is never parsed as a formula


# --------------------------------------------------------------------------- publish
def publish(client: SheetsClient, tabs: list[tuple[str, Table]]) -> None:
    """Replace each tab's contents with its table. Either every tab changes or none does."""
    sheets = client.sheet_properties()

    leftovers = [s["sheetId"] for s in sheets if s["title"].startswith(STAGING_PREFIX)]
    if leftovers:
        log.info("Removing %d staging tab(s) left behind by an earlier run", len(leftovers))
        client.batch_update([{"deleteSheet": {"sheetId": sid}} for sid in leftovers])
        sheets = [s for s in sheets if s["sheetId"] not in leftovers]

    existing = {s["title"].casefold(): s for s in sheets}    # Sheets tab names are case-insensitive
    _check_cell_budget(sheets, existing, tabs)

    # Phase 1: hidden staging tabs, plus any target tab that doesn't exist yet.
    adds = [_add_sheet(STAGING_PREFIX + tab, *_shape(table), hidden=True) for tab, table in tabs]
    adds += [_add_sheet(tab, 1, 1) for tab, _ in tabs if tab.casefold() not in existing]
    created = [reply["addSheet"]["properties"] for reply in client.batch_update(adds)]
    staging = {
        props["title"][len(STAGING_PREFIX):]: props["sheetId"]
        for props in created
        if props["title"].startswith(STAGING_PREFIX)
    }
    for props in created:
        if not props["title"].startswith(STAGING_PREFIX):
            existing[props["title"].casefold()] = props
    targets = {tab: existing[tab.casefold()]["sheetId"] for tab, _ in tabs}

    try:
        # Phase 2: fill the staging tabs.
        for tab, table in tabs:
            _write_rows(client, staging[tab], [list(table.columns), *table.rows])

        # Phase 3: the atomic swap.
        commit: list[dict] = []
        for tab, table in tabs:
            commit += _replace_requests(staging[tab], targets[tab], table)
        commit += [{"deleteSheet": {"sheetId": sid}} for sid in staging.values()]
        client.batch_update(commit)
    except BaseException:
        _delete_quietly(client, staging.values())
        raise


def _shape(table: Table) -> tuple[int, int]:
    return len(table.rows) + 1, len(table.columns)          # +1 for the header row


def _grid_cells(props: dict) -> int:
    grid = props.get("gridProperties", {})
    return grid.get("rowCount", 0) * grid.get("columnCount", 0)


def _check_cell_budget(sheets: list[dict], existing: dict[str, dict], tabs: list[tuple[str, Table]]) -> None:
    current = sum(_grid_cells(s) for s in sheets)
    peak = final = current
    for tab, table in tabs:
        rows, cols = _shape(table)
        new = rows * cols
        old = _grid_cells(existing[tab.casefold()]) if tab.casefold() in existing else 0
        peak += new + max(new - old, 0)          # staging copy + target growth, before staging is deleted
        final += new - old
    if peak > CELL_LIMIT:
        raise PipelineError(
            f"Publishing needs up to {peak:,} cells including staging, over Google Sheets' "
            f"{CELL_LIMIT:,}-cell limit per spreadsheet. Aggregate further or lower max_rows."
        )
    if final > CELL_LIMIT * CELL_WARN_RATIO:
        log.warning("Spreadsheet will use %s cells, %.0f%% of the limit", f"{final:,}", 100 * final / CELL_LIMIT)


def _add_sheet(title: str, rows: int, cols: int, hidden: bool = False) -> dict:
    return {"addSheet": {"properties": {
        "title": title,
        "hidden": hidden,
        "gridProperties": {"rowCount": rows, "columnCount": cols},
    }}}


def _grid_range(sheet_id: int, rows: int, cols: int) -> dict:
    return {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": rows, "startColumnIndex": 0, "endColumnIndex": cols}


def _write_rows(client: SheetsClient, sheet_id: int, rows: list[list[Value]]) -> None:
    """Write rows starting at A1, splitting into requests of at most ~MAX_REQUEST_BYTES."""
    chunk: list[dict] = []
    chunk_bytes = 0
    start = 0
    for index, row in enumerate(rows):
        data = {"values": [to_cell(v) for v in row]}
        size = len(json.dumps(data))
        if chunk and chunk_bytes + size > MAX_REQUEST_BYTES:
            client.batch_update([_update_cells(sheet_id, start, chunk)])
            chunk, chunk_bytes, start = [], 0, index
        chunk.append(data)
        chunk_bytes += size
    if chunk:
        client.batch_update([_update_cells(sheet_id, start, chunk)])


def _update_cells(sheet_id: int, row_index: int, rows: list[dict]) -> dict:
    return {"updateCells": {
        "start": {"sheetId": sheet_id, "rowIndex": row_index, "columnIndex": 0},
        "rows": rows,
        "fields": "userEnteredValue",
    }}


def _replace_requests(source_id: int, target_id: int, table: Table) -> list[dict]:
    rows, cols = _shape(table)
    reqs = [
        {"updateSheetProperties": {
            "properties": {"sheetId": target_id, "gridProperties": {"rowCount": rows, "columnCount": cols}},
            "fields": "gridProperties.rowCount,gridProperties.columnCount",
        }},
        {"updateCells": {"range": {"sheetId": target_id}, "fields": "userEnteredValue,userEnteredFormat"}},
        {"copyPaste": {
            "source": _grid_range(source_id, rows, cols),
            "destination": _grid_range(target_id, rows, cols),
            "pasteType": "PASTE_NORMAL",
        }},
    ]
    for col, kind in enumerate(column_kinds(table)):
        if kind in NUMBER_FORMATS:
            reqs.append({"repeatCell": {
                "range": {"sheetId": target_id, "startRowIndex": 1, "endRowIndex": rows,
                          "startColumnIndex": col, "endColumnIndex": col + 1},
                "cell": {"userEnteredFormat": {"numberFormat": NUMBER_FORMATS[kind]}},
                "fields": "userEnteredFormat.numberFormat",
            }})
    return reqs


def _delete_quietly(client: SheetsClient, sheet_ids: Iterable[int]) -> None:
    ids = list(sheet_ids)
    if not ids:
        return
    try:
        client.batch_update([{"deleteSheet": {"sheetId": sid}} for sid in ids])
    except Exception:
        log.warning("Could not delete staging tabs; the next run removes them")
