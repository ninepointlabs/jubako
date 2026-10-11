"""The one storage interface the app and the MCP server both talk to.

Every backend (SQLite, PostgreSQL, MySQL/MariaDB) implements `Storage`, so
nothing above this layer needs to know which engine is underneath.
"""

from __future__ import annotations

import datetime as _dt
import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field as dc_field
from typing import Any

from ..errors import BadName, TableMissing
from ..fields import INTERNAL_PREFIX, LEGACY_INTERNAL_PREFIX, Field, coerce, is_safe_name
from ..filters import normalise_filter, normalise_sort, order_clause, where_clause

#: Table that remembers each table's declared fields and labels.
META_TABLE = f"{INTERNAL_PREFIX}tables"
#: Table that remembers database-level facts (title, when it was made).
INFO_TABLE = f"{INTERNAL_PREFIX}info"

ROW_ID = "id"


@dataclass
class TableInfo:
    name: str
    fields: list[Field]
    row_count: int = 0


@dataclass
class DatabaseInfo:
    title: str
    backend: str
    location: str
    tables: list[str] = dc_field(default_factory=list)


def check_name(name: str, *, what: str = "name") -> str:
    """Refuse anything that is not a plain, safe identifier."""
    if not is_safe_name(name):
        raise BadName(
            f"That {what} cannot be used: {name!r}. "
            "Use letters, numbers and underscores, starting with a letter."
        )
    return name


def check_user_table(name: str) -> str:
    check_name(name, what="table name")
    if name.lower().startswith(INTERNAL_PREFIX):
        raise BadName(f"Names starting with {INTERNAL_PREFIX!r} are kept for Jubako itself.")
    return name


def as_field_value(value: Any, field_type: str | None) -> Any:
    """Present a stored value the way its field type means it.

    SQLite keeps yes/no as 1/0 and dates as text; this is where that becomes
    a real `True` or `False` again, so every backend looks the same.
    """
    value = to_jsonable(value)
    if value is None or field_type is None:
        return value
    if field_type == "boolean":
        return bool(value)
    return value


def to_jsonable(value: Any) -> Any:
    """Make a value safe to hand to JSON (dates become ISO strings)."""
    if isinstance(value, _dt.datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    return value


class Storage(ABC):
    """A live connection to one database."""

    backend: str = "unknown"

    # -- lifecycle -----------------------------------------------------
    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- plumbing each backend fills in --------------------------------
    @abstractmethod
    def quote(self, name: str) -> str:
        """Wrap an already-validated identifier for this engine."""

    @abstractmethod
    def placeholder(self, index: int) -> str:
        """The parameter marker this driver wants."""

    @abstractmethod
    def column_sql(self, field: Field) -> str:
        """The engine's column type for one Jubako field."""

    @abstractmethod
    def primary_key_sql(self) -> str:
        """The engine's auto-numbering primary key column."""

    @abstractmethod
    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        """Run a statement. Returns a cursor-like object."""

    @abstractmethod
    def query(self, sql: str, params: Sequence[Any] = ()) -> list[tuple]:
        """Run a query and return all rows."""

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def last_row_id(self, cursor: Any, table: str) -> int | None: ...

    @abstractmethod
    def location(self) -> str:
        """Where this database lives, in words a person can read."""

    @abstractmethod
    def real_table_names(self) -> list[str]:
        """Every table the engine actually has, including our own."""

    # -- shared behaviour ----------------------------------------------
    def marks(self, count: int) -> str:
        return ", ".join(self.placeholder(i) for i in range(count))

    def ensure_meta(self) -> None:
        self.migrate_legacy_meta()
        self.execute(
            f"CREATE TABLE IF NOT EXISTS {self.quote(INFO_TABLE)} "
            f"({self.quote('key')} VARCHAR(64) PRIMARY KEY, {self.quote('value')} TEXT)"
        )
        self.execute(
            f"CREATE TABLE IF NOT EXISTS {self.quote(META_TABLE)} "
            f"({self.quote('table_name')} VARCHAR(64) PRIMARY KEY, {self.quote('spec')} TEXT)"
        )
        self.commit()

    def migrate_legacy_meta(self) -> None:
        """Rename `omadb_*` bookkeeping tables from before the rename to Jubako."""
        existing = {name.lower(): name for name in self.real_table_names()}
        renamed = False
        for new in (INFO_TABLE, META_TABLE):
            old = LEGACY_INTERNAL_PREFIX + new[len(INTERNAL_PREFIX):]
            if old in existing and new not in existing:
                self.execute(f"ALTER TABLE {self.quote(existing[old])} RENAME TO {self.quote(new)}")
                renamed = True
        if renamed:
            self.commit()

    def set_info(self, key: str, value: str) -> None:
        self.execute(
            f"DELETE FROM {self.quote(INFO_TABLE)} WHERE {self.quote('key')} = {self.placeholder(0)}",
            (key,),
        )
        self.execute(
            f"INSERT INTO {self.quote(INFO_TABLE)} ({self.quote('key')}, {self.quote('value')}) "
            f"VALUES ({self.marks(2)})",
            (key, value),
        )
        self.commit()

    def get_info(self, key: str, default: str = "") -> str:
        rows = self.query(
            f"SELECT {self.quote('value')} FROM {self.quote(INFO_TABLE)} "
            f"WHERE {self.quote('key')} = {self.placeholder(0)}",
            (key,),
        )
        return str(rows[0][0]) if rows else default

    @property
    def title(self) -> str:
        return self.get_info("title", "Database")

    def describe(self) -> DatabaseInfo:
        return DatabaseInfo(
            title=self.title,
            backend=self.backend,
            location=self.location(),
            tables=self.list_tables(),
        )

    # -- tables ---------------------------------------------------------
    def list_tables(self) -> list[str]:
        """The tables people made, newest names sorted, minus our own."""
        names = [
            name
            for name in self.real_table_names()
            if not name.lower().startswith(INTERNAL_PREFIX)
        ]
        return sorted(names)

    def has_table(self, table: str) -> bool:
        return table in self.list_tables()

    def create_table(self, table: str, fields: Sequence[Field], *, if_exists: str = "error") -> TableInfo:
        """Make a new table. `if_exists` is "error", "skip" or "replace"."""
        check_user_table(table)
        if not fields:
            raise BadName("A table needs at least one field.")
        for field in fields:
            check_name(field.name, what="field name")
            if field.name == ROW_ID:
                raise BadName(f"{ROW_ID!r} is added for you; pick another field name.")

        if self.has_table(table):
            if if_exists == "skip":
                return self.describe_table(table)
            if if_exists == "replace":
                self.drop_table(table)
            else:
                raise BadName(f"There is already a table called {table!r}.")

        columns = [self.primary_key_sql()] + [self.column_sql(f) for f in fields]
        self.execute(f"CREATE TABLE {self.quote(table)} ({', '.join(columns)})")
        self.remember_fields(table, fields)
        self.commit()
        return TableInfo(name=table, fields=list(fields), row_count=0)

    # -- fields --------------------------------------------------------
    def add_field(self, table: str, field: Field) -> TableInfo:
        """Add a column. Rows already there get nothing in it (blank)."""
        info = self.describe_table(table)
        check_name(field.name, what="field name")
        if field.name == ROW_ID:
            raise BadName(f"{ROW_ID!r} is kept for the row number; pick another name.")
        if field.name in {f.name for f in info.fields}:
            raise BadName(f"There is already a field called {field.name!r} in {table!r}.")
        self.execute(f"ALTER TABLE {self.quote(table)} ADD COLUMN {self.column_sql(field)}")
        fields = list(info.fields) + [field]
        self.remember_fields(table, fields)
        self.commit()
        return TableInfo(name=table, fields=fields, row_count=info.row_count)

    def drop_field(self, table: str, name: str) -> TableInfo:
        """Remove one column and everything in it. The table keeps at least one field."""
        info = self.describe_table(table)
        check_name(name, what="field name")
        if name == ROW_ID:
            raise BadName("The row number cannot be removed.")
        if name not in {f.name for f in info.fields}:
            raise BadName(f"The table {table!r} has no field called {name!r}.")
        if len(info.fields) == 1:
            raise BadName("A table needs at least one field. Delete the table instead.")
        self.execute(f"ALTER TABLE {self.quote(table)} DROP COLUMN {self.quote(name)}")
        remaining = [f for f in info.fields if f.name != name]
        self.remember_fields(table, remaining)
        self.commit()
        return TableInfo(name=table, fields=remaining, row_count=info.row_count)

    def rename_field(self, table: str, old: str, new: str, *, label: str | None = None) -> TableInfo:
        """Change a column's name (and, if given, its label). Rows are untouched."""
        info = self.describe_table(table)
        check_name(old, what="field name")
        check_name(new, what="field name")
        names = [f.name for f in info.fields]
        if old not in names:
            raise BadName(f"The table {table!r} has no field called {old!r}.")
        if new == ROW_ID:
            raise BadName(f"{ROW_ID!r} is kept for the row number; pick another name.")
        if new != old and new in names:
            raise BadName(f"There is already a field called {new!r} in {table!r}.")
        if new != old:
            self.execute(
                f"ALTER TABLE {self.quote(table)} RENAME COLUMN {self.quote(old)} TO {self.quote(new)}"
            )
        fields = [
            Field(name=new if f.name == old else f.name, type=f.type,
                  label=(label if label is not None else f.label) if f.name == old else f.label)
            for f in info.fields
        ]
        self.remember_fields(table, fields)
        self.commit()
        return TableInfo(name=table, fields=fields, row_count=info.row_count)

    def relabel_field(self, table: str, name: str, label: str) -> TableInfo:
        """Change only the words people see for a field."""
        return self.rename_field(table, name, name, label=label)

    def drop_table(self, table: str) -> None:
        check_user_table(table)
        self.execute(f"DROP TABLE IF EXISTS {self.quote(table)}")
        self.execute(
            f"DELETE FROM {self.quote(META_TABLE)} WHERE {self.quote('table_name')} = {self.placeholder(0)}",
            (table,),
        )
        self.commit()

    def remember_fields(self, table: str, fields: Sequence[Field]) -> None:
        spec = json.dumps(
            [{"name": f.name, "type": f.type, "label": f.label or f.title} for f in fields]
        )
        self.execute(
            f"DELETE FROM {self.quote(META_TABLE)} WHERE {self.quote('table_name')} = {self.placeholder(0)}",
            (table,),
        )
        self.execute(
            f"INSERT INTO {self.quote(META_TABLE)} "
            f"({self.quote('table_name')}, {self.quote('spec')}) VALUES ({self.marks(2)})",
            (table, spec),
        )

    def remembered_fields(self, table: str) -> list[Field] | None:
        rows = self.query(
            f"SELECT {self.quote('spec')} FROM {self.quote(META_TABLE)} "
            f"WHERE {self.quote('table_name')} = {self.placeholder(0)}",
            (table,),
        )
        if not rows:
            return None
        try:
            spec = json.loads(rows[0][0])
        except (TypeError, ValueError):
            return None
        return [Field(name=item["name"], type=item["type"], label=item.get("label")) for item in spec]

    def describe_table(self, table: str) -> TableInfo:
        check_user_table(table)
        if not self.has_table(table):
            raise TableMissing(f"This database has no table called {table!r}.")
        fields = self.remembered_fields(table) or self.introspect_fields(table)
        return TableInfo(name=table, fields=fields, row_count=self.count_rows(table))

    @abstractmethod
    def introspect_fields(self, table: str) -> list[Field]:
        """Read the engine's own column list, for tables we did not make."""

    # -- rows -------------------------------------------------------------
    def count_rows(self, table: str, *, where: dict[str, Any] | None = None) -> int:
        check_user_table(table)
        sql = f"SELECT COUNT(*) FROM {self.quote(table)}"
        params: list[Any] = []
        if where:
            info = self.describe_table(table)
            clause, params = where_clause(self, normalise_filter(info.fields, where))
            sql += f" WHERE {clause}"
        rows = self.query(sql, params)
        return int(rows[0][0]) if rows else 0

    def add_row(self, table: str, values: dict[str, Any]) -> int | None:
        info = self.describe_table(table)
        known = {f.name: f for f in info.fields}
        unknown = [name for name in values if name not in known and name != ROW_ID]
        if unknown:
            raise BadName(f"This table has no field called {unknown[0]!r}.")

        names = [name for name in known if name in values]
        params = [coerce(values[name], known[name].type) for name in names]
        if not names:
            raise BadName("Give at least one field a value.")
        sql = (
            f"INSERT INTO {self.quote(table)} "
            f"({', '.join(self.quote(n) for n in names)}) VALUES ({self.marks(len(names))})"
        )
        cursor = self.execute(sql, params)
        row_id = self.last_row_id(cursor, table)
        self.commit()
        return row_id

    def add_rows(self, table: str, fields: Sequence[Field], rows: Sequence[Sequence[Any]]) -> int:
        """Bulk insert already-typed rows. Used by the spreadsheet import."""
        if not rows:
            return 0
        names = [f.name for f in fields]
        sql = (
            f"INSERT INTO {self.quote(table)} "
            f"({', '.join(self.quote(n) for n in names)}) VALUES ({self.marks(len(names))})"
        )
        count = 0
        for row in rows:
            self.execute(sql, list(row))
            count += 1
        self.commit()
        return count

    def list_rows(
        self,
        table: str,
        *,
        limit: int = 100,
        offset: int = 0,
        order_by: str | None = None,
        descending: bool = False,
        where: dict[str, Any] | None = None,
        sort: Any = None,
    ) -> dict[str, Any]:
        """A page of rows.

        `where` is a filter (see `filters.py`), or None for all. `sort` is a
        list of {field, descending}; `order_by` / `descending` is the older
        one-field way of saying the same.
        """
        info = self.describe_table(table)
        limit = max(1, min(int(limit), 5000))
        offset = max(0, int(offset))
        filter_spec = normalise_filter(info.fields, where)
        clause, params = where_clause(self, filter_spec)
        if not sort and (order_by or descending):
            sort = [{"field": order_by or ROW_ID, "descending": descending}]
        sort_spec = normalise_sort(info.fields, sort)

        columns = [ROW_ID] + [f.name for f in info.fields]
        order = order_clause(self, sort_spec)
        sql = (
            f"SELECT {', '.join(self.quote(c) for c in columns)} FROM {self.quote(table)} "
            + (f"WHERE {clause} " if clause else "")
            + (f"ORDER BY {order} " if order else "")
            + f"LIMIT {limit} OFFSET {offset}"
        )
        rows = self.query(sql, params)
        # Column 0 is the row id; the rest line up with the fields.
        types = [None] + [f.type for f in info.fields]
        matching = self.count_rows(table, where=filter_spec) if filter_spec else info.row_count
        return {
            "table": table,
            "fields": [{"name": f.name, "type": f.type, "label": f.title} for f in info.fields],
            "columns": columns,
            "rows": [
                [as_field_value(value, types[index]) for index, value in enumerate(row)]
                for row in rows
            ],
            "limit": limit,
            "offset": offset,
            "total": matching,
            "total_all": info.row_count,
            "filter": filter_spec,
            "sort": sort_spec,
        }

    def update_row(self, table: str, row_id: int, values: dict[str, Any]) -> bool:
        info = self.describe_table(table)
        known = {f.name: f for f in info.fields}
        unknown = [name for name in values if name not in known]
        if unknown:
            raise BadName(f"This table has no field called {unknown[0]!r}.")
        names = list(values)
        if not names:
            return False
        assignments = ", ".join(
            f"{self.quote(name)} = {self.placeholder(i)}" for i, name in enumerate(names)
        )
        params = [coerce(values[name], known[name].type) for name in names]
        params.append(int(row_id))
        cursor = self.execute(
            f"UPDATE {self.quote(table)} SET {assignments} "
            f"WHERE {self.quote(ROW_ID)} = {self.placeholder(len(names))}",
            params,
        )
        self.commit()
        return bool(getattr(cursor, "rowcount", 0))

    def delete_row(self, table: str, row_id: int) -> bool:
        check_user_table(table)
        if not self.has_table(table):
            raise TableMissing(f"This database has no table called {table!r}.")
        cursor = self.execute(
            f"DELETE FROM {self.quote(table)} WHERE {self.quote(ROW_ID)} = {self.placeholder(0)}",
            (int(row_id),),
        )
        self.commit()
        return bool(getattr(cursor, "rowcount", 0))
