"""Helpers and fixtures for tests that hit a REAL Google Sheet. Skipped unless both variables are set:

    GOOGLE_APPLICATION_CREDENTIALS   path to a service-account key (or other ADC credentials)
    SNOWSHEETS_LIVE_SHEET_ID         a scratch spreadsheet shared with that account as Editor

Every tab these tests create starts with LIVE_PREFIX and is deleted afterwards.
Never point SNOWSHEETS_LIVE_SHEET_ID at a spreadsheet holding real data.
"""
from __future__ import annotations

import os

import pytest

from snowsheets.config import STAGING_PREFIX
from snowsheets.sheets import SheetsClient

LIVE_PREFIX = "live_"
SHEET_ID = os.environ.get("SNOWSHEETS_LIVE_SHEET_ID", "")

# Apply to a test module with `pytestmark = LIVE`.
LIVE = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (SHEET_ID and os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")),
        reason="set SNOWSHEETS_LIVE_SHEET_ID and GOOGLE_APPLICATION_CREDENTIALS to run",
    ),
]


def _delete_test_tabs(client: SheetsClient) -> None:
    doomed = [t["sheetId"] for t in client.sheet_properties()
              if t["title"].startswith((LIVE_PREFIX, STAGING_PREFIX))]
    if doomed:
        client.batch_update([{"deleteSheet": {"sheetId": sid}} for sid in doomed])


@pytest.fixture(scope="session")
def live_client():
    """One real client for the whole session, so its write pacing (quota) is shared by every test."""
    client = SheetsClient(SHEET_ID)
    _delete_test_tabs(client)            # leftovers from an interrupted earlier run
    yield client
    _delete_test_tabs(client)


@pytest.fixture
def tab_name(request):
    """A unique tab name per test, e.g. live_test_realistic_table."""
    return (LIVE_PREFIX + request.node.name)[:80]


def read_grid(client: SheetsClient, title: str) -> list[list[dict]]:
    """Read a tab back from Google: values and number formats, padded to the tab's full grid.

    Same shape as FakeSheets.read_grid(), so the same assertions run on real and fake data.
    """
    body = client._request("GET", client._url, params={
        "ranges": f"'{title}'",
        "includeGridData": "true",
        "fields": "sheets(properties(title,hidden,gridProperties),"
                  "data(rowData(values(userEnteredValue,userEnteredFormat(numberFormat)))))",
    })
    sheet = body["sheets"][0]
    grid = sheet["properties"]["gridProperties"]
    row_data = sheet.get("data", [{}])[0].get("rowData", [])
    cells = []
    for r in range(grid["rowCount"]):
        values = row_data[r].get("values", []) if r < len(row_data) else []
        cells.append([values[c] if c < len(values) else {} for c in range(grid["columnCount"])])
    return cells


def tab_props(client: SheetsClient, title: str) -> dict:
    return next(t for t in client.sheet_properties() if t["title"] == title)
