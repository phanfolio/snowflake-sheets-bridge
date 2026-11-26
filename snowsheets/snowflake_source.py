"""Snowflake side: key-pair connection, running a query, and normalising values to plain Python types."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Union

import snowflake.connector
from cryptography.hazmat.primitives import serialization

from .errors import PipelineError

Value = Union[None, bool, int, float, str, date, datetime, time]
MAX_CELL_CHARS = 50_000        # Google Sheets' per-cell limit


@dataclass(frozen=True)
class Table:
    columns: list[str]
    rows: list[list[Value]]


def connect() -> snowflake.connector.SnowflakeConnection:
    return snowflake.connector.connect(
        account=_env("SNOWFLAKE_ACCOUNT"),
        user=_env("SNOWFLAKE_USER"),
        private_key=_private_key_der(),
        warehouse=_env("SNOWFLAKE_WAREHOUSE"),
        role=_env("SNOWFLAKE_ROLE"),
        database=os.environ.get("SNOWFLAKE_DATABASE") or None,
        schema=os.environ.get("SNOWFLAKE_SCHEMA") or None,
        login_timeout=60,
        network_timeout=120,
        session_parameters={
            "QUERY_TAG": "snowsheets",
            "STATEMENT_TIMEOUT_IN_SECONDS": 600,
        },
    )


def fetch(conn: snowflake.connector.SnowflakeConnection, sql: str, max_rows: int) -> Table:
    """Run one query, fetching at most max_rows + 1 rows so an oversized result is caught cheaply."""
    with conn.cursor() as cur:
        cur.execute(sql)
        columns = [col[0] for col in cur.description]
        rows = [[normalize(v) for v in row] for row in cur.fetchmany(max_rows + 1)]
    return Table(columns=columns, rows=rows)


def normalize(value: object) -> Value:
    """Map a Snowflake connector value onto the small set of types the Sheets writer understands."""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        return value[:MAX_CELL_CHARS]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, datetime):                  # before `date`: datetime subclasses date
        if value.tzinfo is not None:                 # TIMESTAMP_TZ / _LTZ -> UTC; Sheets has no time zones
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        # Whole seconds only. Found live: Tableau read 23:59:59.999999 as Null, because the stored
        # day fraction rounds up to the next day. Truncating can never cross a day boundary.
        return value.replace(microsecond=0)
    if isinstance(value, date):
        return value
    if isinstance(value, time):
        return value.replace(tzinfo=None, microsecond=0)
    if isinstance(value, (bytes, bytearray)):        # BINARY
        return value.hex()[:MAX_CELL_CHARS]
    return str(value)[:MAX_CELL_CHARS]               # anything else, e.g. unparsed VARIANT


# --------------------------------------------------------------------------- credentials
def _env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise PipelineError(f"Missing environment variable {name}")
    return value


def _private_key_der() -> bytes:
    """Load the PEM private key (env text or file) and return the unencrypted DER bytes the connector expects."""
    pem_text = os.environ.get("SNOWFLAKE_PRIVATE_KEY", "")
    key_path = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH", "")
    if pem_text:
        pem = pem_text.replace("\\n", "\n").encode()
    elif key_path:
        pem = Path(key_path).expanduser().read_bytes()
    else:
        raise PipelineError("Set SNOWFLAKE_PRIVATE_KEY (PEM text) or SNOWFLAKE_PRIVATE_KEY_PATH (file)")

    passphrase = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE") or None
    try:
        key = serialization.load_pem_private_key(pem, password=passphrase.encode() if passphrase else None)
    except (ValueError, TypeError) as exc:
        raise PipelineError("Snowflake private key could not be loaded (wrong format or passphrase)") from exc
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
