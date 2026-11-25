"""Test doubles and BI-readiness helpers.

FakeSheets stands in for snowsheets.sheets.SheetsClient. It applies batchUpdate requests the way
Google does and is strict on purpose: invalid JSON, writes outside the grid, duplicate tab names,
the 10M-cell limit, over-long text and hiding every tab all raise, so sizing or typing bugs fail
tests instead of reaching a real Sheet. Each batch is all-or-nothing, like the real API.
"""
from __future__ import annotations

import copy
import json

from snowsheets.sheets import CELL_LIMIT, SheetsApiError

MAX_CELL_CHARS = 50_000


class FakeSheets:
    def __init__(self, tabs: dict[str, tuple[int, int]] | None = None) -> None:
        self.sheets: dict[int, dict] = {}
        self.calls: list[list[dict]] = []
        self.fail_when = None                     # callable(reqs) -> bool, to inject an API failure
        self._next_id = 1
        for title, (rows, cols) in (tabs or {"Sheet1": (1000, 26)}).items():
            self._addSheet({"properties": {"title": title,
                                           "gridProperties": {"rowCount": rows, "columnCount": cols}}})

    # ------------------------------------------------------------ SheetsClient interface
    def sheet_properties(self) -> list[dict]:
        return [copy.deepcopy(s["props"]) for s in self.sheets.values()]

    def batch_update(self, reqs: list[dict]) -> list[dict]:
        json.dumps(reqs, allow_nan=False)         # Google rejects NaN / Infinity in request JSON
        self.calls.append(reqs)
        if self.fail_when and self.fail_when(reqs):
            raise SheetsApiError("injected failure")
        snapshot, next_id = copy.deepcopy(self.sheets), self._next_id
        try:
            replies = [self._apply(req) for req in reqs]
            self._check_spreadsheet()
        except Exception:
            self.sheets, self._next_id = snapshot, next_id    # all-or-nothing
            raise
        return replies

    # ------------------------------------------------------------ inspection for tests
    def titles(self) -> list[str]:
        return [s["props"]["title"] for s in self.sheets.values()]

    def props(self, title: str) -> dict:
        return self._by_title(title)["props"]

    def read_grid(self, title: str) -> list[list[dict]]:
        """Every cell of a tab, row by row, exactly as large as the tab's grid."""
        sheet = self._by_title(title)
        grid = sheet["props"]["gridProperties"]
        return [[copy.deepcopy(sheet["cells"].get((r, c), {})) for c in range(grid["columnCount"])]
                for r in range(grid["rowCount"])]

    def seed(self, title: str, values: list[list[object]]) -> None:
        """Put pre-existing data in a tab (as a person or an earlier tool might have)."""
        sheet = self._by_title(title)
        for r, row in enumerate(values):
            for c, value in enumerate(row):
                key = "numberValue" if isinstance(value, (int, float)) else "stringValue"
                sheet["cells"][(r, c)] = {"userEnteredValue": {key: value},
                                          "userEnteredFormat": {"numberFormat": {"type": "DATE"}}}

    # ------------------------------------------------------------ request handlers
    def _apply(self, req: dict) -> dict:
        ((kind, body),) = req.items()
        handler = getattr(self, f"_{kind}", None)
        if handler is None:
            raise SheetsApiError(f"FakeSheets does not support {kind}")
        return handler(body)

    def _addSheet(self, body: dict) -> dict:
        props = copy.deepcopy(body["properties"])
        if any(t.casefold() == props["title"].casefold() for t in self.titles()):
            raise SheetsApiError(f'A sheet with the name "{props["title"]}" already exists')
        props.setdefault("hidden", False)
        props.setdefault("gridProperties", {"rowCount": 1000, "columnCount": 26})
        props["sheetId"] = self._next_id
        self._next_id += 1
        self.sheets[props["sheetId"]] = {"props": props, "cells": {}}
        return {"addSheet": {"properties": copy.deepcopy(props)}}

    def _deleteSheet(self, body: dict) -> dict:
        self._sheet(body["sheetId"])
        del self.sheets[body["sheetId"]]
        return {}

    def _updateSheetProperties(self, body: dict) -> dict:
        if body["fields"] != "gridProperties.rowCount,gridProperties.columnCount":
            raise SheetsApiError(f"FakeSheets does not support fields {body['fields']}")
        sheet = self._sheet(body["properties"]["sheetId"])
        rows = body["properties"]["gridProperties"]["rowCount"]
        cols = body["properties"]["gridProperties"]["columnCount"]
        if rows < 1 or cols < 1:
            raise SheetsApiError("grid must have at least one row and column")
        sheet["props"]["gridProperties"] = {"rowCount": rows, "columnCount": cols}
        sheet["cells"] = {k: v for k, v in sheet["cells"].items() if k[0] < rows and k[1] < cols}
        return {}

    def _updateCells(self, body: dict) -> dict:
        fields = body["fields"].split(",")
        if "rows" not in body:                    # no rows: clear those fields across the range
            sheet = self._sheet(body["range"]["sheetId"])
            for key in self._range_keys(sheet, body["range"]):
                for field in fields:
                    sheet["cells"].get(key, {}).pop(field, None)
            return {}
        start = body["start"]
        sheet = self._sheet(start["sheetId"])
        for dr, row in enumerate(body["rows"]):
            for dc, new in enumerate(row.get("values", [])):
                key = (start["rowIndex"] + dr, start["columnIndex"] + dc)
                self._require_in_grid(sheet, key)
                cell = sheet["cells"].setdefault(key, {})
                for field in fields:
                    if field in new and new[field] != {"stringValue": ""}:   # Google drops "" (verified live)
                        cell[field] = copy.deepcopy(new[field])
                    else:
                        cell.pop(field, None)
        return {}

    def _copyPaste(self, body: dict) -> dict:
        if body.get("pasteType") != "PASTE_NORMAL":
            raise SheetsApiError("FakeSheets only supports PASTE_NORMAL")
        src_rng, dst_rng = body["source"], body["destination"]
        src, dst = self._sheet(src_rng["sheetId"]), self._sheet(dst_rng["sheetId"])
        src_keys = list(self._range_keys(src, src_rng))
        dst_keys = list(self._range_keys(dst, dst_rng))
        if len(src_keys) != len(dst_keys):
            raise SheetsApiError("FakeSheets requires equal-sized copyPaste ranges")
        for s_key, d_key in zip(src_keys, dst_keys):
            if s_key in src["cells"]:
                dst["cells"][d_key] = copy.deepcopy(src["cells"][s_key])
            else:
                dst["cells"].pop(d_key, None)
        return {}

    def _repeatCell(self, body: dict) -> dict:
        sheet = self._sheet(body["range"]["sheetId"])
        path = body["fields"].split(".")
        value = body["cell"]
        for part in path:
            value = value[part]
        for key in self._range_keys(sheet, body["range"]):
            node = sheet["cells"].setdefault(key, {})
            for part in path[:-1]:
                node = node.setdefault(part, {})
            node[path[-1]] = copy.deepcopy(value)
        return {}

    # ------------------------------------------------------------ helpers
    def _check_spreadsheet(self) -> None:
        total = sum(s["props"]["gridProperties"]["rowCount"] * s["props"]["gridProperties"]["columnCount"]
                    for s in self.sheets.values())
        if total > CELL_LIMIT:
            raise SheetsApiError("This action would increase the number of cells above the limit")
        if not any(not s["props"].get("hidden") for s in self.sheets.values()):
            raise SheetsApiError("You can't remove or hide all the sheets in a document")
        for sheet in self.sheets.values():
            for cell in sheet["cells"].values():
                text = cell.get("userEnteredValue", {}).get("stringValue")
                if text is not None and len(text) > MAX_CELL_CHARS:
                    raise SheetsApiError(f"Your input contains more than the maximum of {MAX_CELL_CHARS} characters")

    def _sheet(self, sheet_id: int) -> dict:
        if sheet_id not in self.sheets:
            raise SheetsApiError(f"No grid with id: {sheet_id}")
        return self.sheets[sheet_id]

    def _by_title(self, title: str) -> dict:
        return next(s for s in self.sheets.values() if s["props"]["title"].casefold() == title.casefold())

    @staticmethod
    def _require_in_grid(sheet: dict, key: tuple[int, int]) -> None:
        grid = sheet["props"]["gridProperties"]
        if key[0] >= grid["rowCount"] or key[1] >= grid["columnCount"]:
            raise SheetsApiError(f"Range exceeds grid limits at row {key[0]}, column {key[1]}")

    def _range_keys(self, sheet: dict, rng: dict):
        grid = sheet["props"]["gridProperties"]
        r0, r1 = rng.get("startRowIndex", 0), rng.get("endRowIndex", grid["rowCount"])
        c0, c1 = rng.get("startColumnIndex", 0), rng.get("endColumnIndex", grid["columnCount"])
        if r1 > grid["rowCount"] or c1 > grid["columnCount"]:
            raise SheetsApiError("Range exceeds grid limits")
        for r in range(r0, r1):
            for c in range(c0, c1):
                yield (r, c)


# ---------------------------------------------------------------- reading a tab like a BI tool
def cell_value(cell: dict):
    entered = cell.get("userEnteredValue", {})
    for key in ("numberValue", "stringValue", "boolValue"):
        if key in entered:
            return entered[key]
    return None


def cell_kind(cell: dict) -> str | None:
    entered = cell.get("userEnteredValue", {})
    if "formulaValue" in entered:
        return "formula"
    for key, kind in (("numberValue", "number"), ("stringValue", "string"), ("boolValue", "bool")):
        if key in entered:
            return kind
    return None


def number_format(cell: dict) -> str | None:
    return cell.get("userEnteredFormat", {}).get("numberFormat", {}).get("type")


def assert_bi_ready(grid: list[list[dict]], header: list[str], n_rows: int) -> None:
    """What Tableau's and Power BI's Google Sheets connectors need to import a tab as a clean table."""
    assert len(grid) == n_rows + 1, "no stray rows: every grid row is the header or a data row"
    assert all(len(row) == len(header) for row in grid), "no stray columns"

    names = [cell_value(c) for c in grid[0]]
    assert names == header, "row 1 is the header, in query order"
    assert all(isinstance(n, str) and n.strip() for n in names), "header cells are non-empty text"
    assert len(set(names)) == len(names), "header names are unique"
    assert all(number_format(c) is None for c in grid[0]), "header cells carry no number format"

    for col, name in enumerate(names):
        cells = [row[col] for row in grid[1:]]
        kinds = {cell_kind(c) for c in cells} - {None}
        assert "formula" not in kinds, f"{name}: no formulas, only values"
        assert len(kinds) <= 1, f"{name}: one value type per column, got {kinds}"
        formats = {number_format(c) for c in cells if cell_kind(c) is not None}
        assert len(formats) <= 1, f"{name}: one number format per column, got {formats}"
