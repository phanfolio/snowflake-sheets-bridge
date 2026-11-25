"""Load a project's config.

Settings resolve in this order (later wins):
    built-in  <  defaults.yml  <  project .yml  <  individual dataset entry
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import PipelineError

DEFAULTS_FILENAME = "defaults.yml"
REPO_ROOT_MARKER = "pyproject.toml"

STAGING_PREFIX = "__staging__"
MAX_TAB_CHARS = 80              # Sheets allows 100; leaves room for STAGING_PREFIX
ON_EMPTY_CHOICES = ("fail", "allow")

BUILTIN_SETTINGS: dict[str, Any] = {
    "refresh_log_tab": "_refresh_log",
    "on_empty": "fail",
    "max_rows": 100_000,
}
PROJECT_KEYS = set(BUILTIN_SETTINGS) | {"datasets"}
DATASET_KEYS = {"name", "sql", "tab", "columns", "on_empty", "max_rows"}
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class ConfigError(PipelineError):
    """The YAML config or a SQL file it points to is invalid."""


@dataclass(frozen=True)
class Dataset:
    name: str
    sql_path: Path
    sql: str
    tab: str
    columns: tuple[str, ...] | None     # None = no schema lock
    on_empty: str
    max_rows: int


@dataclass(frozen=True)
class Project:
    name: str
    config_file: Path
    refresh_log_tab: str
    datasets: tuple[Dataset, ...]


def find_project_file(project_dir: Path) -> Path:
    """A project's config is the single .yml/.yaml file at its folder root, whatever it is named."""
    if not project_dir.is_dir():
        raise ConfigError(f"Project folder not found: {project_dir}")
    found = sorted(p for p in project_dir.iterdir() if p.is_file() and p.suffix in {".yml", ".yaml"})
    if len(found) != 1:
        names = ", ".join(p.name for p in found) or "none"
        raise ConfigError(
            f"{project_dir}: expected exactly one .yml file at the project root, found {len(found)} ({names})"
        )
    return found[0]


def find_defaults_file(project_dir: Path) -> Path | None:
    """The nearest defaults.yml above the project folder, searching no higher than the repo root.

    Located from the project folder rather than from this package's install path, so it works
    whether the package is installed editable (uv sync) or as a regular wheel.
    """
    for folder in project_dir.resolve().parents:
        candidate = folder / DEFAULTS_FILENAME
        if candidate.is_file():
            return candidate
        if (folder / REPO_ROOT_MARKER).is_file():
            break
    return None


def load_project(project_dir: Path, defaults_file: Path | None = None) -> Project:
    config_file = find_project_file(project_dir)
    if defaults_file is None:
        defaults_file = find_defaults_file(project_dir)

    settings = dict(BUILTIN_SETTINGS)
    if defaults_file is not None and defaults_file.is_file():
        settings.update(_read_mapping(defaults_file, allowed=set(BUILTIN_SETTINGS)))

    raw = _read_mapping(config_file, allowed=PROJECT_KEYS)
    settings.update({key: value for key, value in raw.items() if key in BUILTIN_SETTINGS})

    refresh_log_tab = _tab(settings["refresh_log_tab"], f"{config_file.name}: refresh_log_tab")

    entries = raw.get("datasets")
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"{config_file.name}: 'datasets' must be a non-empty list")
    datasets = tuple(_dataset(entry, i, settings, config_file) for i, entry in enumerate(entries))

    _unique([d.name for d in datasets], f"{config_file.name}: duplicate dataset name")
    _unique(
        [d.tab.casefold() for d in datasets] + [refresh_log_tab.casefold()],
        f"{config_file.name}: duplicate tab name (case-insensitive, refresh_log_tab included)",
    )
    return Project(
        name=project_dir.resolve().name,
        config_file=config_file,
        refresh_log_tab=refresh_log_tab,
        datasets=datasets,
    )


# --------------------------------------------------------------------------- helpers
def _dataset(entry: Any, index: int, settings: dict[str, Any], config_file: Path) -> Dataset:
    where = f"{config_file.name}: datasets[{index}]"
    if not isinstance(entry, dict):
        raise ConfigError(f"{where} must be a mapping")
    _only_keys(entry, DATASET_KEYS, where)

    name = entry.get("name")
    if not isinstance(name, str) or not _NAME.match(name):
        raise ConfigError(f"{where}: 'name' is required and may only contain letters, digits, '_' and '-'")
    where = f"{config_file.name}: dataset '{name}'"

    sql_rel = entry.get("sql")
    if not isinstance(sql_rel, str) or not sql_rel:
        raise ConfigError(f"{where}: 'sql' is required (a .sql path relative to {config_file.name})")
    sql_path = config_file.parent / sql_rel
    if not sql_path.is_file():
        raise ConfigError(f"{where}: SQL file not found: {sql_rel}")
    sql = sql_path.read_text(encoding="utf-8").strip()
    if not sql:
        raise ConfigError(f"{where}: SQL file is empty: {sql_rel}")

    columns = entry.get("columns")
    if columns is not None:
        if not isinstance(columns, list) or not columns or not all(isinstance(c, str) and c for c in columns):
            raise ConfigError(f"{where}: 'columns' must be a non-empty list of column names")
        _unique(columns, f"{where}: duplicate name in 'columns'")
        columns = tuple(columns)

    on_empty = entry.get("on_empty", settings["on_empty"])
    if on_empty not in ON_EMPTY_CHOICES:
        raise ConfigError(f"{where}: 'on_empty' must be one of: {', '.join(ON_EMPTY_CHOICES)}")

    max_rows = entry.get("max_rows", settings["max_rows"])
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
        raise ConfigError(f"{where}: 'max_rows' must be a positive integer")

    return Dataset(
        name=name,
        sql_path=sql_path,
        sql=sql,
        tab=_tab(entry.get("tab", name), f"{where}: tab"),
        columns=columns,
        on_empty=on_empty,
        max_rows=max_rows,
    )


def _read_mapping(path: Path, allowed: set[str]) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name}: invalid YAML: {exc}") from None
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path.name}: top level must be a mapping of keys to values")
    _only_keys(raw, allowed, path.name)
    return raw


def _only_keys(mapping: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(str(key) for key in mapping if key not in allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {', '.join(unknown)}; allowed: {', '.join(sorted(allowed))}")


def _tab(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ConfigError(f"{where} must be a non-empty name without leading or trailing spaces")
    if len(value) > MAX_TAB_CHARS:
        raise ConfigError(f"{where} must be at most {MAX_TAB_CHARS} characters")
    if value.startswith(STAGING_PREFIX):
        raise ConfigError(f"{where} must not start with the reserved prefix {STAGING_PREFIX}")
    return value


def _unique(values: list, message: str) -> None:
    seen: set = set()
    dupes: set = set()
    for value in values:
        (dupes if value in seen else seen).add(value)
    if dupes:
        raise ConfigError(f"{message}: {', '.join(sorted(map(str, dupes)))}")
