"""SQLite backend: one file, no server. This is the simple default."""

from __future__ import annotations

import datetime as _dt
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..errors import DatabaseExists, DatabaseMissing, JubakoError
from ..fields import BOOLEAN, DATE, INTEGER, LOOKUP, REAL, TEXT, Field
from ..paths import database_path
from .base import ROW_ID, Storage, check_name

_COLUMN_TYPES = {
    TEXT: "TEXT",
    INTEGER: "INTEGER",
    REAL: "REAL",
    DATE: "TEXT",
    BOOLEAN: "INTEGER",
    LOOKUP: "INTEGER",  # the other row's id
}

_FROM_SQLITE = {
    "INTEGER": INTEGER,
    "REAL": REAL,
    "NUMERIC": REAL,
    "TEXT": TEXT,
    "BLOB": TEXT,
}


def _adapt_date(value: _dt.date) -> str:
    return value.isoformat()


sqlite3.register_adapter(_dt.date, _adapt_date)
sqlite3.register_adapter(_dt.datetime, lambda v: v.isoformat(sep=" "))


class SQLiteStorage(Storage):
    backend = "sqlite"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")

    # -- lifecycle ------------------------------------------------------
    @classmethod
    def create(cls, path: str, *, title: str = "", overwrite: bool = False) -> "SQLiteStorage":
        target = database_path(path)
        if target.exists() and not overwrite:
            raise DatabaseExists(f"There is already a database at {target}.")
        if target.exists() and overwrite:
            target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        storage = cls(target)
        storage.ensure_meta()
        storage.set_info("title", title or target.stem)
        storage.set_info("created", _dt.datetime.now().isoformat(timespec="seconds"))
        storage.set_info("backend", cls.backend)
        try:
            target.chmod(0o600)
        except OSError:
            pass
        return storage

    @classmethod
    def open(cls, path: str) -> "SQLiteStorage":
        target = database_path(path)
        if not target.exists():
            raise DatabaseMissing(f"There is no database at {target}.")
        storage = cls(target)
        storage.ensure_meta()
        return storage

    def close(self) -> None:
        try:
            self.connection.commit()
        finally:
            self.connection.close()

    # -- plumbing -------------------------------------------------------
    def quote(self, name: str) -> str:
        return f'"{check_name(name)}"'

    def placeholder(self, index: int) -> str:
        return "?"

    def column_sql(self, field: Field) -> str:
        return f"{self.quote(field.name)} {_COLUMN_TYPES[field.type]}"

    def primary_key_sql(self) -> str:
        return f"{self.quote(ROW_ID)} INTEGER PRIMARY KEY AUTOINCREMENT"

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        return self.connection.execute(sql, tuple(params))

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[tuple]:
        return list(self.connection.execute(sql, tuple(params)).fetchall())

    def commit(self) -> None:
        self.connection.commit()

    def last_row_id(self, cursor: sqlite3.Cursor, table: str) -> int | None:
        return cursor.lastrowid

    def location(self) -> str:
        return str(self.path)

    def real_table_names(self) -> list[str]:
        rows = self.query(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        return [str(row[0]) for row in rows]

    def introspect_fields(self, table: str) -> list[Field]:
        rows = self.query(f"PRAGMA table_info({self.quote(table)})")
        fields = []
        for row in rows:
            name = str(row[1])
            if name == ROW_ID:
                continue
            declared = str(row[2] or "TEXT").upper().split("(")[0]
            fields.append(Field(name=name, type=_FROM_SQLITE.get(declared, TEXT)))
        return fields

    def column_names(self, table: str) -> list[str]:
        return [str(row[1]) for row in self.query(f"PRAGMA table_info({self.quote(table)})")]

    def add_row_id_column(self, table: str) -> None:
        """SQLite cannot add a primary key to a table, so the table is rebuilt with one, in one go."""
        fields = self.introspect_fields(table)
        names = ", ".join(self.quote(f.name) for f in fields)
        temporary = f"jubako_rebuild_{table}"[:63]
        self.connection.commit()
        try:
            self.connection.execute("BEGIN")
            self.connection.execute(f"DROP TABLE IF EXISTS {self.quote(temporary)}")
            columns = [self.primary_key_sql()] + [self.column_sql(f) for f in fields]
            self.connection.execute(f"CREATE TABLE {self.quote(temporary)} ({', '.join(columns)})")
            self.connection.execute(
                f"INSERT INTO {self.quote(temporary)} ({names}) SELECT {names} FROM {self.quote(table)}"
            )
            self.connection.execute(f"DROP TABLE {self.quote(table)}")
            self.connection.execute(f"ALTER TABLE {self.quote(temporary)} RENAME TO {self.quote(table)}")
            self.connection.commit()
        except sqlite3.Error as error:
            self.connection.rollback()
            raise JubakoError(f"Could not add a row number: {error}") from error
