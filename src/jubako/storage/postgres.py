"""PostgreSQL backend. Optional: needs a server and the `psycopg` driver.

Install the driver with `pip install 'jubako[postgres]'` (or the Arch
package `python-psycopg`).
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Sequence
from typing import Any

from ..errors import BackendNotAvailable, DatabaseMissing, JubakoError
from ..fields import BOOLEAN, DATE, INTEGER, REAL, TEXT, Field
from .base import ROW_ID, Storage, check_name

_COLUMN_TYPES = {
    TEXT: "TEXT",
    INTEGER: "BIGINT",
    REAL: "DOUBLE PRECISION",
    DATE: "DATE",
    BOOLEAN: "BOOLEAN",
}

_FROM_PG = {
    "bigint": INTEGER,
    "integer": INTEGER,
    "smallint": INTEGER,
    "double precision": REAL,
    "real": REAL,
    "numeric": REAL,
    "date": DATE,
    "timestamp without time zone": DATE,
    "boolean": BOOLEAN,
}


def _driver():
    try:
        import psycopg  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise BackendNotAvailable(
            "PostgreSQL needs the 'psycopg' driver. "
            "Install it with: pip install 'jubako[postgres]'"
        ) from exc
    return psycopg


def connection_string(
    *,
    host: str = "localhost",
    port: int = 5432,
    database: str = "",
    user: str = "",
    password: str = "",
    url: str = "",
) -> str:
    """Build a libpq connection string, or pass a URL straight through."""
    if url:
        return url
    parts = [f"host={host}", f"port={int(port)}"]
    if database:
        parts.append(f"dbname={database}")
    if user:
        parts.append(f"user={user}")
    if password:
        parts.append(f"password={password}")
    return " ".join(parts)


class PostgresStorage(Storage):
    backend = "postgres"

    def __init__(self, dsn: str) -> None:
        psycopg = _driver()
        self._dsn = dsn
        try:
            self.connection = psycopg.connect(dsn)
        except Exception as exc:  # driver raises its own error types
            raise JubakoError(f"Could not reach the PostgreSQL server: {exc}") from exc

    @classmethod
    def create(cls, dsn: str, *, title: str = "", overwrite: bool = False) -> "PostgresStorage":
        """Set Jubako up inside an existing PostgreSQL database.

        The server and the database itself are the user's to create; we add
        our bookkeeping tables to the one they point us at.
        """
        storage = cls(dsn)
        storage.ensure_meta()
        if overwrite:
            for table in storage.list_tables():
                storage.drop_table(table)
        storage.set_info("title", title or "Database")
        storage.set_info("created", _dt.datetime.now().isoformat(timespec="seconds"))
        storage.set_info("backend", cls.backend)
        return storage

    @classmethod
    def open(cls, dsn: str) -> "PostgresStorage":
        storage = cls(dsn)
        storage.ensure_meta()
        return storage

    def close(self) -> None:
        try:
            self.connection.commit()
        finally:
            self.connection.close()

    def quote(self, name: str) -> str:
        return f'"{check_name(name)}"'

    def placeholder(self, index: int) -> str:
        return "%s"

    def column_sql(self, field: Field) -> str:
        return f"{self.quote(field.name)} {_COLUMN_TYPES[field.type]}"

    def primary_key_sql(self) -> str:
        return f"{self.quote(ROW_ID)} BIGSERIAL PRIMARY KEY"

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        cursor = self.connection.cursor()
        cursor.execute(sql, tuple(params))
        return cursor

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[tuple]:
        cursor = self.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()
        return [tuple(row) for row in rows]

    def commit(self) -> None:
        self.connection.commit()

    def last_row_id(self, cursor: Any, table: str) -> int | None:
        rows = self.query(f"SELECT MAX({self.quote(ROW_ID)}) FROM {self.quote(table)}")
        return int(rows[0][0]) if rows and rows[0][0] is not None else None

    def location(self) -> str:
        # Never echo the password back to the user or into a log.
        return _redact(self._dsn)

    def real_table_names(self) -> list[str]:
        rows = self.query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
        )
        return [str(row[0]) for row in rows]

    def introspect_fields(self, table: str) -> list[Field]:
        rows = self.query(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s ORDER BY ordinal_position",
            (table,),
        )
        if not rows:
            raise DatabaseMissing(f"PostgreSQL has no table called {table!r}.")
        return [
            Field(name=str(name), type=_FROM_PG.get(str(kind).lower(), TEXT))
            for name, kind in rows
            if str(name) != ROW_ID
        ]

    def column_names(self, table: str) -> list[str]:
        rows = self.query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s ORDER BY ordinal_position",
            (table,),
        )
        return [str(row[0]) for row in rows]

    def add_row_id_column(self, table: str) -> None:
        # PostgreSQL fills a new BIGSERIAL column for the rows already there.
        self.execute(f"ALTER TABLE {self.quote(table)} ADD COLUMN {self.primary_key_sql()}")


def _redact(dsn: str) -> str:
    out = []
    for chunk in dsn.split():
        if chunk.lower().startswith("password="):
            out.append("password=***")
        else:
            out.append(chunk)
    text = " ".join(out)
    if "://" in text and "@" in text:
        scheme, rest = text.split("://", 1)
        creds, host = rest.rsplit("@", 1)
        if ":" in creds:
            user = creds.split(":", 1)[0]
            creds = f"{user}:***"
        text = f"{scheme}://{creds}@{host}"
    return text
