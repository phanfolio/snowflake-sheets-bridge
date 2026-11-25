"""SheetsClient's HTTP behaviour: retries, give-up, and error messages. The HTTP session is faked."""
from __future__ import annotations

import pytest
import requests

from snowsheets import sheets
from snowsheets.sheets import MAX_ATTEMPTS, SheetsApiError


class FakeResponse:
    def __init__(self, status: int, body: dict | None = None) -> None:
        self.status_code = status
        self.ok = 200 <= status < 300
        self._body = body or {}

    def json(self) -> dict:
        return self._body


class FakeSession:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method, url, timeout, **kwargs):
        self.calls.append((method, url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def client_with(monkeypatch):
    def make(*responses):
        session = FakeSession(responses)
        monkeypatch.setattr(sheets.google.auth, "default", lambda scopes: (object(), None))
        monkeypatch.setattr(sheets, "AuthorizedSession", lambda credentials: session)
        monkeypatch.setattr(sheets.time, "sleep", lambda seconds: None)
        return sheets.SheetsClient("sheet123"), session
    return make


def test_retries_quota_errors_then_succeeds(client_with):
    client, session = client_with(FakeResponse(429), FakeResponse(200, {"replies": [{}]}))
    assert client.batch_update([{"deleteSheet": {"sheetId": 1}}]) == [{}]
    assert len(session.calls) == 2
    assert session.calls[0][1].endswith("/sheet123:batchUpdate")


def test_retries_connection_errors(client_with):
    client, session = client_with(requests.ConnectionError(), FakeResponse(200, {"replies": []}))
    client.batch_update([{"deleteSheet": {"sheetId": 1}}])
    assert len(session.calls) == 2


def test_gives_up_after_max_attempts(client_with):
    client, session = client_with(*[FakeResponse(503)] * MAX_ATTEMPTS)
    with pytest.raises(SheetsApiError, match="HTTP 503"):
        client.batch_update([{"deleteSheet": {"sheetId": 1}}])
    assert len(session.calls) == MAX_ATTEMPTS


def test_permission_errors_fail_fast_with_googles_reason(client_with):
    body = {"error": {"status": "PERMISSION_DENIED", "message": "The caller does not have permission"}}
    client, session = client_with(FakeResponse(403, body))
    with pytest.raises(SheetsApiError, match="403 PERMISSION_DENIED: The caller does not have permission"):
        client.batch_update([{"deleteSheet": {"sheetId": 1}}])
    assert len(session.calls) == 1


def test_sheet_properties_asks_only_for_tab_properties(client_with):
    body = {"sheets": [{"properties": {"sheetId": 0, "title": "Sheet1"}}]}
    client, session = client_with(FakeResponse(200, body))
    assert client.sheet_properties() == [{"sheetId": 0, "title": "Sheet1"}]
    assert session.calls[0][2]["params"] == {"fields": "sheets.properties"}


def test_empty_batch_sends_nothing(client_with):
    client, session = client_with()
    assert client.batch_update([]) == []
    assert session.calls == []
