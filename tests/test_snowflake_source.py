"""Snowflake side: key loading, connection parameters and fetching. The connector itself is faked."""
from __future__ import annotations

from decimal import Decimal

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from snowsheets import snowflake_source
from snowsheets.errors import PipelineError
from snowsheets.snowflake_source import _private_key_der, fetch


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def pem(key, passphrase: bytes | None = None) -> str:
    encryption = (serialization.BestAvailableEncryption(passphrase) if passphrase
                  else serialization.NoEncryption())
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption).decode()


def loads_back(der: bytes):
    return serialization.load_der_private_key(der, password=None)


# ---------------------------------------------------------------- private key
def test_pem_text_becomes_unencrypted_der(monkeypatch, rsa_key):
    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY", pem(rsa_key))
    assert loads_back(_private_key_der()).private_numbers() == rsa_key.private_numbers()


def test_pem_with_escaped_newlines_is_accepted(monkeypatch, rsa_key):
    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY", pem(rsa_key).replace("\n", "\\n"))
    loads_back(_private_key_der())


def test_key_file_path_is_accepted(monkeypatch, rsa_key, tmp_path):
    path = tmp_path / "rsa_key.p8"
    path.write_text(pem(rsa_key))
    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_PATH", str(path))
    loads_back(_private_key_der())


def test_encrypted_key_with_passphrase(monkeypatch, rsa_key):
    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY", pem(rsa_key, b"s3cret"))
    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE", "s3cret")
    loads_back(_private_key_der())


def test_wrong_passphrase_gives_a_safe_message(monkeypatch, rsa_key):
    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY", pem(rsa_key, b"s3cret"))
    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE", "Tr0ub4dor-guess")
    with pytest.raises(PipelineError, match="could not be loaded") as info:
        _private_key_der()
    assert "s3cret" not in str(info.value) and "Tr0ub4dor" not in str(info.value)


def test_missing_key_is_reported():
    with pytest.raises(PipelineError, match="SNOWFLAKE_PRIVATE_KEY"):
        _private_key_der()


# ---------------------------------------------------------------- connect
def test_connect_passes_settings_from_environment(monkeypatch, rsa_key):
    for name, value in {"SNOWFLAKE_ACCOUNT": "org-acct", "SNOWFLAKE_USER": "SVC", "SNOWFLAKE_WAREHOUSE": "WH",
                        "SNOWFLAKE_ROLE": "ROLE", "SNOWFLAKE_PRIVATE_KEY": pem(rsa_key)}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("SNOWFLAKE_DATABASE", raising=False)
    captured = {}
    monkeypatch.setattr(snowflake_source.snowflake.connector, "connect", lambda **kw: captured.update(kw))

    snowflake_source.connect()
    assert (captured["account"], captured["user"], captured["warehouse"], captured["role"]) == \
        ("org-acct", "SVC", "WH", "ROLE")
    assert captured["database"] is None
    assert isinstance(captured["private_key"], bytes)
    assert captured["session_parameters"]["QUERY_TAG"] == "snowsheets"


def test_connect_requires_account(monkeypatch):
    monkeypatch.delenv("SNOWFLAKE_ACCOUNT", raising=False)
    with pytest.raises(PipelineError, match="SNOWFLAKE_ACCOUNT"):
        snowflake_source.connect()


# ---------------------------------------------------------------- fetch
class FakeCursor:
    def __init__(self, columns, rows):
        self.description = [(name, None) for name in columns]
        self.rows, self.requested, self.sql = rows, None, None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql):
        self.sql = sql

    def fetchmany(self, size):
        self.requested = size
        return self.rows[:size]


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def test_fetch_normalizes_values_and_reads_at_most_max_rows_plus_one():
    cursor = FakeCursor(["A", "B"], [(Decimal("1.00"), "x")] * 100)
    table = fetch(FakeConnection(cursor), "select a, b from t", max_rows=10)
    assert cursor.sql == "select a, b from t"
    assert cursor.requested == 11
    assert table.columns == ["A", "B"]
    assert len(table.rows) == 11 and table.rows[0] == [1, "x"]
