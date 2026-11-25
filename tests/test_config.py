"""Config discovery, precedence and validation."""
from __future__ import annotations

import pytest

from conftest import REPO_ROOT
from snowsheets.config import ConfigError, find_defaults_file, load_project


def test_the_repos_own_example_project_is_valid():
    project = load_project(REPO_ROOT / "projects" / "tpch_sample")
    assert project.name == "tpch_sample"
    assert [d.name for d in project.datasets] == ["daily_orders", "revenue_by_region"]


def test_precedence_builtin_defaults_project_dataset(make_project):
    project = load_project(make_project(yml="""
        on_empty: allow
        datasets:
          - name: a
            sql: queries/daily_sales.sql
          - name: b
            sql: queries/daily_sales.sql
            tab: Bee
            max_rows: 10
            on_empty: fail
            columns: [X, Y]
    """))
    a, b = project.datasets
    assert (a.tab, a.max_rows, a.on_empty, a.columns) == ("a", 50, "allow", None)       # defaults.yml max_rows
    assert (b.tab, b.max_rows, b.on_empty, b.columns) == ("Bee", 10, "fail", ("X", "Y"))
    assert project.refresh_log_tab == "_refresh_log"                                    # built-in


def test_config_file_name_does_not_matter(make_project):
    folder = make_project("anything")
    (folder / "anything.yml").rename(folder / "whatever.yaml")
    assert load_project(folder).config_file.name == "whatever.yaml"


def test_defaults_file_is_found_at_the_repo_root(make_project, repo):
    folder = make_project()
    assert find_defaults_file(folder) == (repo / "defaults.yml").resolve()


def test_defaults_search_stops_at_the_repo_root(tmp_path):
    (tmp_path / "defaults.yml").write_text("max_rows: 1\n")            # above the repo: must be ignored
    repo = tmp_path / "repo"
    folder = repo / "projects" / "p"
    (folder / "queries").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("")
    (folder / "p.yml").write_text("datasets: [{name: a, sql: queries/a.sql}]\n")
    (folder / "queries" / "a.sql").write_text("select 1")
    assert find_defaults_file(folder) is None
    assert load_project(folder).datasets[0].max_rows == 100_000


@pytest.mark.parametrize("yml, sql, extra, message", [
    ("datasets: []", None, (), "non-empty list"),
    ("datasets: [{name: a, sql: queries/daily_sales.sql, colums: [X]}]", None, (), "unknown key(s) colums"),
    ("datasets: [{name: a, sql: queries/daily_sales.sql}, {name: b, sql: queries/daily_sales.sql, tab: A}]",
     None, (), "duplicate tab"),
    ("datasets: [{name: a, sql: queries/daily_sales.sql, tab: _REFRESH_LOG}]", None, (), "duplicate tab"),
    ("datasets: [{name: a, sql: queries/daily_sales.sql}, {name: a, sql: queries/daily_sales.sql, tab: z}]",
     None, (), "duplicate dataset name"),
    ("datasets: [{name: a, sql: queries/missing.sql}]", None, (), "SQL file not found"),
    ("datasets: [{name: a, sql: queries/daily_sales.sql}]", {"daily_sales.sql": "  \n"}, (), "SQL file is empty"),
    ("datasets: [{name: a, sql: queries/daily_sales.sql, tab: __staging__x}]", None, (), "reserved prefix"),
    ("datasets: [{name: a, sql: queries/daily_sales.sql, tab: ' padded'}]", None, (), "leading or trailing"),
    ("datasets: [{name: a, sql: queries/daily_sales.sql, tab: " + "x" * 81 + "}]", None, (), "at most 80"),
    ("datasets: [{name: a, sql: queries/daily_sales.sql, on_empty: maybe}]", None, (), "on_empty"),
    ("datasets: [{name: a, sql: queries/daily_sales.sql, max_rows: true}]", None, (), "max_rows"),
    ("datasets: [{name: a, sql: queries/daily_sales.sql, max_rows: 0}]", None, (), "max_rows"),
    ("datasets: [{name: 'bad name', sql: queries/daily_sales.sql}]", None, (), "'name'"),
    ("datasets: [{name: a, sql: queries/daily_sales.sql, columns: [X, X]}]", None, (), "duplicate name in 'columns'"),
    ("datasets: [{name: a, sql: queries/daily_sales.sql, columns: []}]", None, (), "'columns'"),
    ("- just a list", None, (), "top level must be a mapping"),
    ("datasets: [unclosed", None, (), "invalid YAML"),
    ("datasets: [{name: a, sql: queries/daily_sales.sql}]", None, ("other.yml",), "exactly one .yml"),
])
def test_invalid_config_is_rejected(make_project, yml, sql, extra, message):
    folder = make_project(yml=yml, sql=sql, extra_files=extra)
    with pytest.raises(ConfigError) as info:
        load_project(folder)
    assert message in str(info.value)


def test_unknown_key_in_defaults_file_is_rejected(make_project, repo):
    (repo / "defaults.yml").write_text("datasets: []\n")
    with pytest.raises(ConfigError, match="defaults.yml: unknown key"):
        load_project(make_project())


def test_missing_project_folder(repo):
    with pytest.raises(ConfigError, match="Project folder not found"):
        load_project(repo / "projects" / "nope")
