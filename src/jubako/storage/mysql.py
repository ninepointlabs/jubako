"""MySQL / MariaDB backend. Optional: needs a server and the `PyMySQL` driver.

Install the driver with `pip install 'jubako[mysql]'` (or the Arch
package `python-pymysql`).
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Sequence
from typing import Any

from ..errors import BackendNotAvailable, DatabaseMissing, JubakoError
from ..fields import BOOLEAN, DATE, INTEGER, LOOKUP, REAL, TEXT, Field
from .base import ROW_ID, Storage, check_name

_COLUMN_TYPES = {
    TEXT: "TEXT",
    INTEGER: "BIGINT",
    REAL: "DOUBLE",
    DATE: "DATE",
    BOOLEAN: "TINYINT(1)",
    LOOKUP: "BIGINT",  # the other row's id
}

_FROM_MYSQL = {
    "bigint": INTEGER,
    "int": INTEGER,
    "smallint": INTEGER,
    "tinyint": BOOLEAN,
    "double": REAL,
    "float": REAL,
    "decimal": REAL,
    "date": DATE,
    "datetime": DATE,
    "timestamp": DATE,
}


def _driver():
    try:
        import pymysql  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise BackendNotAvailable(
            "MySQL / MariaDB needs the 'PyMySQL' driver. "
            "Install it with: pip install 'jubako[mysql]'"
        ) from exc
    return pymysql


class MySQLStorage(Storage):
    backend = "mysql"

    def __init__(
        self,
        *,
        host: str = "localhost",
        port: int = 3306,
        database: str = "",
        user: str = "",
        password: str = "",
    ) -> None:
        pymysql = _driver()
        self._where = f"{user}@{host}:{port}/{database}"
        try:
            self.connection = pymysql.connect(
                host=host,
                port=int(port),
                user=user or None,
                password=password or "",
                database=database or None,
                charset="utf8mb4",
                autocommit=False,
            )
        except Exception as exc:  # driver raises its own error types
            raise JubakoError(f"Could not reach the MySQL/MariaDB server: {exc}") from exc

    @classmethod
    def create(cls, *, title: str = "", overwrite: bool = False, **connect: Any) -> "MySQLStorage":
        """Set Jubako up inside an existing MySQL/MariaDB database."""
        storage = cls(**connect)
        storage.ensure_meta()
        if overwrite:
            for table in storage.list_tables():
                storage.drop_table(table)
        storage.set_info("title", title or connect.get("database", "Database"))
        storage.set_info("created", _dt.datetime.now().isoformat(timespec="seconds"))
        storage.set_info("backend", cls.backend)
        return storage

    @classmethod
    def open(cls, **connect: Any) -> "MySQLStorage":
        storage = cls(**connect)
        storage.ensure_meta()
        return storage

    def close(self) -> None:
        try:
            self.connection.commit()
        finally:
            self.connection.close()

    def quote(self, name: str) -> str:
        return f"`{check_name(name)}`"

    def placeholder(self, index: int) -> str:
        return "%s"

    def column_sql(self, field: Field) -> str:
        return f"{self.quote(field.name)} {_COLUMN_TYPES[field.type]}"

    def primary_key_sql(self) -> str:
        return f"{self.quote(ROW_ID)} BIGINT AUTO_INCREMENT PRIMARY KEY"

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
        value = getattr(cursor, "lastrowid", None)
        return int(value) if value else None

    def location(self) -> str:
        return self._where

    def real_table_names(self) -> list[str]:
        rows = self.query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'"
        )
        return [str(row[0]) for row in rows]

    def introspect_fields(self, table: str) -> list[Field]:
        rows = self.query(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = %s ORDER BY ordinal_position",
            (table,),
        )
        if not rows:
            raise DatabaseMissing(f"MySQL has no table called {table!r}.")
        return [
            Field(name=str(name), type=_FROM_MYSQL.get(str(kind).lower(), TEXT))
            for name, kind in rows
            if str(name) != ROW_ID
        ]

    def column_names(self, table: str) -> list[str]:
        rows = self.query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = %s ORDER BY ordinal_position",
            (table,),
        )
        return [str(row[0]) for row in rows]

    def add_row_id_column(self, table: str) -> None:
        # MySQL numbers the rows already there as it adds the column.
        self.execute(f"ALTER TABLE {self.quote(table)} ADD COLUMN {self.primary_key_sql()} FIRST")

    def unique_column_sql(self, field: Field) -> str:
        # A TEXT column can only be indexed on a prefix; 191 characters fits utf8mb4 in every row format.
        return f"{self.quote(field.name)}(191)" if field.type == TEXT else self.quote(field.name)

    def drop_index_sql(self, index: str, table: str) -> str:
        return f"DROP INDEX {self.quote(index)} ON {self.quote(table)}"
