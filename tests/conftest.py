"""Shared fixtures. Nothing here touches the network: Snowflake and Google are always faked."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from fakes import FakeSheets

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_PROJECT_YML = """
datasets:
  - name: daily_sales
    sql: queries/daily_sales.sql
"""


@pytest.fixture
def fake_sheets() -> FakeSheets:
    """A spreadsheet that, like a brand-new Google Sheet, starts with one tab: Sheet1."""
    return FakeSheets()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Tests never see real credentials from the developer's shell."""
    for name in ("GOOGLE_SHEET_ID", "GITHUB_SHA", "VERBOSE_ERRORS", "SNOWFLAKE_PRIVATE_KEY",
                 "SNOWFLAKE_PRIVATE_KEY_PATH", "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A minimal repo: pyproject.toml marks the root, defaults.yml holds shared settings."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\n")
    (tmp_path / "defaults.yml").write_text("max_rows: 50\n")
    return tmp_path


@pytest.fixture
def make_project(repo: Path):
    """Factory: make_project(name, yml, sql={file: text}, extra_files=[...]) -> project folder."""

    def make(name: str = "proj", yml: str = DEFAULT_PROJECT_YML, sql: dict[str, str] | None = None,
             extra_files: tuple[str, ...] = ()) -> Path:
        folder = repo / "projects" / name
        (folder / "queries").mkdir(parents=True)
        (folder / f"{name}.yml").write_text(textwrap.dedent(yml))
        for filename, text in (sql or {"daily_sales.sql": "select 1"}).items():
            (folder / "queries" / filename).write_text(text)
        for filename in extra_files:
            (folder / filename).write_text("")
        return folder

    return make
