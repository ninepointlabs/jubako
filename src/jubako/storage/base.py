"""The one storage interface the app and the MCP server both talk to.

Every backend (SQLite, PostgreSQL, MySQL/MariaDB) implements `Storage`, so
nothing above this layer needs to know which engine is underneath.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field as dc_field, replace
from typing import Any

from ..errors import BadName, JubakoError, LookupMissing, TableMissing
from ..fields import (
    INTERNAL_PREFIX,
    LEGACY_INTERNAL_PREFIX,
    LOOKUP,
    TEXT,
    UNIQUE_TYPES,
    Field,
    coerce,
    field_dict,
    field_from_dict,
    is_safe_name,
)
from ..filters import lookup_text_sql, normalise_filter, normalise_sort, order_clause, where_clause

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
    #: False for a table made outside Jubako without an `id`: it can be read, not edited row by row.
    has_row_id: bool = True


NO_ROW_ID = (
    "This table came from outside Jubako and has no row number, so its rows cannot be "
    "changed one at a time. Add a row number to it first."
)


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


def to_json(value: Any) -> str:
    """JSON text for something Jubako keeps in its info table. A filter on a date holds a real
    date, so dates (and anything else `to_jsonable` knows) are written as text."""

    def fallback(item: Any) -> Any:
        safe = to_jsonable(item)
        if safe is item:
            raise TypeError(f"Object of type {type(item).__name__} is not JSON serializable")
        return safe

    return json.dumps(value, default=fallback)


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

        for field in fields:
            if field.unique:
                self._check_unique_type(field)
            if field.type == LOOKUP:
                self._check_lookup(table, field, fields)
        columns = [self.primary_key_sql()] + [self.column_sql(f) for f in fields]
        self.execute(f"CREATE TABLE {self.quote(table)} ({', '.join(columns)})")
        for field in fields:
            if field.unique:
                self._create_unique_index(table, field)
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
        if field.unique:
            self._check_unique_type(field)
        if field.type == LOOKUP:
            self._check_lookup(table, field, info.fields)
        self.execute(f"ALTER TABLE {self.quote(table)} ADD COLUMN {self.column_sql(field)}")
        if field.unique:
            self._create_unique_index(table, field)  # rows already there are blank, and blanks may repeat
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
        showing = [(src, f) for src, f in self.lookups_into(table) if f.show == name and not (src == table and f.name == name)]
        if showing:
            src, f = showing[0]
            raise JubakoError(
                f"{f.title} in {src} shows this field, so it cannot be deleted. "
                f"Delete {f.title}, or make it show another field, first."
            )
        if any(f.name == name and f.unique for f in info.fields):
            # SQLite will not drop a column that has an index on it.
            self.execute(self.drop_index_sql(unique_index_name(table, name), table))
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
        renamed_unique = new != old and any(f.name == old and f.unique for f in info.fields)
        if renamed_unique:
            self.execute(self.drop_index_sql(unique_index_name(table, old), table))
        if new != old:
            self.execute(
                f"ALTER TABLE {self.quote(table)} RENAME COLUMN {self.quote(old)} TO {self.quote(new)}"
            )
        fields = [
            replace(f, name=new, label=label if label is not None else f.label) if f.name == old else f
            for f in info.fields
        ]
        if renamed_unique:
            self._create_unique_index(table, next(f for f in fields if f.name == new))
        self.remember_fields(table, fields)
        if new != old:
            self._follow_shown_field(table, old, new)
            fields = self.remembered_fields(table) or fields
        self.commit()
        return TableInfo(name=table, fields=fields, row_count=info.row_count)

    def _follow_shown_field(self, table: str, old: str, new: str) -> None:
        """A field was renamed: lookups (in any table) that show it now show the new name."""
        for src, src_fields in self._all_remembered().items():
            if not any(f.type == LOOKUP and f.target == table and f.show == old for f in src_fields):
                continue
            self.remember_fields(src, [
                replace(f, show=new) if f.type == LOOKUP and f.target == table and f.show == old else f
                for f in src_fields
            ])

    def relabel_field(self, table: str, name: str, label: str) -> TableInfo:
        """Change only the words people see for a field."""
        return self.rename_field(table, name, name, label=label)

    def set_unique(self, table: str, name: str, unique: bool) -> TableInfo:
        """Turn "no repeats" on or off for a field. Refused while values already repeat."""
        info = self.describe_table(table)
        known = {f.name: f for f in info.fields}
        if name not in known:
            raise BadName(f"The table {table!r} has no field called {name!r}.")
        field = known[name]
        if field.unique == bool(unique):
            return info
        if unique:
            self._check_unique_type(field)
            repeats = self.repeated_values(table, name)
            if repeats:
                shown = ", ".join(f"“{_value_text(value)}” ({count} rows)" for value, count in repeats[:3])
                more = f" and {len(repeats) - 3} more" if len(repeats) > 3 else ""
                raise JubakoError(
                    f"{field.title} already repeats, so it cannot be made no-repeats yet: {shown}{more}. "
                    "Change or delete those rows first."
                )
            self._create_unique_index(table, field)
        else:
            self.execute(self.drop_index_sql(unique_index_name(table, name), table))
        fields = [replace(f, unique=bool(unique)) if f.name == name else f for f in info.fields]
        self.remember_fields(table, fields)
        self.commit()
        return TableInfo(name=table, fields=fields, row_count=info.row_count)

    def repeated_values(self, table: str, name: str, *, limit: int = 20) -> list[tuple[Any, int]]:
        """Values that appear in more than one row of a field (blanks do not count)."""
        column = self.quote(name)
        rows = self.query(
            f"SELECT {column}, COUNT(*) FROM {self.quote(table)} WHERE {column} IS NOT NULL "
            f"GROUP BY {column} HAVING COUNT(*) > 1 ORDER BY COUNT(*) DESC LIMIT {int(limit)}"
        )
        return [(to_jsonable(value), int(count)) for value, count in rows]

    def add_row_number(self, table: str) -> TableInfo:
        """Give a table made outside Jubako an automatic `id`, so its rows can be edited."""
        info = self.describe_table(table)
        if info.has_row_id:
            raise JubakoError("This table already has a row number.")
        self.add_row_id_column(table)
        self.remember_fields(table, info.fields)
        self.commit()
        return self.describe_table(table)

    def _check_unique_type(self, field: Field) -> None:
        if field.type not in UNIQUE_TYPES:
            raise JubakoError(f"A yes / no field like {field.title} cannot be no-repeats: it only has two values.")

    def _create_unique_index(self, table: str, field: Field) -> None:
        self.execute(
            f"CREATE UNIQUE INDEX {self.quote(unique_index_name(table, field.name))} "
            f"ON {self.quote(table)} ({self.unique_column_sql(field)})"
        )

    def _check_repeats(self, table: str, fields: dict[str, Field], values: dict[str, Any],
                       row_id: int | None = None) -> None:
        """Say in words which no-repeats field a write would repeat, before the engine refuses it."""
        for name, value in values.items():
            field = fields.get(name)
            if field is None or not field.unique or value is None:
                continue
            sql = f"SELECT COUNT(*) FROM {self.quote(table)} WHERE {self.quote(name)} = {self.placeholder(0)}"
            params: list[Any] = [value]
            if row_id is not None:
                sql += f" AND {self.quote(ROW_ID)} <> {self.placeholder(1)}"
                params.append(int(row_id))
            rows = self.query(sql, params)
            if rows and int(rows[0][0]) > 0:
                raise JubakoError(f"{field.title} cannot repeat: “{_value_text(value)}” is already in another row.")

    def drop_table(self, table: str) -> None:
        check_user_table(table)
        others = [(src, f) for src, f in self.lookups_into(table) if src != table]
        if others:
            src, f = others[0]
            raise JubakoError(
                f"{f.title} in {src} points at rows of {table}, so {table} cannot be deleted. "
                f"Delete {f.title} (or {src}) first."
            )
        self.execute(f"DROP TABLE IF EXISTS {self.quote(table)}")
        self.execute(
            f"DELETE FROM {self.quote(META_TABLE)} WHERE {self.quote('table_name')} = {self.placeholder(0)}",
            (table,),
        )
        self.commit()

    def remember_fields(self, table: str, fields: Sequence[Field]) -> None:
        spec = json.dumps([{**field_dict(f), "label": f.label or f.title} for f in fields])
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
        return [field_from_dict(item) for item in spec]

    def _all_remembered(self) -> dict[str, list[Field]]:
        """Every table Jubako made, with its fields, read in one go."""
        out: dict[str, list[Field]] = {}
        for name, spec in self.query(f"SELECT {self.quote('table_name')}, {self.quote('spec')} FROM {self.quote(META_TABLE)}"):
            try:
                out[str(name)] = [field_from_dict(item) for item in json.loads(spec)]
            except (TypeError, ValueError, KeyError):
                continue
        return out

    def lookups_into(self, table: str) -> list[tuple[str, Field]]:
        """Every lookup field (in any table, this one too) that points at rows of `table`."""
        return [(src, f) for src, fields in self._all_remembered().items()
                for f in fields if f.type == LOOKUP and f.target == table]

    def _check_lookup(self, table: str, field: Field, fields: Sequence[Field] = ()) -> None:
        """A lookup must point at a table with row numbers, and show one of its words fields."""
        if field.target == table:
            target_fields = list(fields)
        else:
            try:
                check_user_table(field.target or "")
                target = self.describe_table(field.target or "")
            except (BadName, TableMissing):
                raise JubakoError(f"There is no table called {field.target!r} for {field.title} to point at.") from None
            if not target.has_row_id:
                raise JubakoError(f"{field.target} has no row numbers yet, so nothing can point at its rows. "
                                  "Add a row number to it first.")
            target_fields = target.fields
        shown = {f.name: f for f in target_fields}.get(field.show or "")
        if shown is None:
            raise JubakoError(f"{field.target} has no field called {field.show!r} for {field.title} to show.")
        if shown.type != TEXT:
            raise JubakoError(f"{field.title} can only show a words field of {field.target}; "
                              f"{shown.title} holds something else.")

    def describe_table(self, table: str) -> TableInfo:
        check_user_table(table)
        if not self.has_table(table):
            raise TableMissing(f"This database has no table called {table!r}.")
        remembered = self.remembered_fields(table)
        if remembered:
            fields, has_row_id = remembered, True
        else:
            # Made outside Jubako: read the engine's columns, and check for a row number.
            fields = self.introspect_fields(table)
            has_row_id = ROW_ID in self.column_names(table)
        return TableInfo(name=table, fields=fields, row_count=self.count_rows(table), has_row_id=has_row_id)

    @abstractmethod
    def introspect_fields(self, table: str) -> list[Field]:
        """Read the engine's own column list, for tables we did not make."""

    @abstractmethod
    def column_names(self, table: str) -> list[str]:
        """Every column the engine has for a table, `id` included."""

    def add_row_id_column(self, table: str) -> None:
        """Give a table made elsewhere Jubako's auto-numbered `id` (each engine has its own way)."""
        raise JubakoError("This kind of database cannot add a row number here.")

    def unique_column_sql(self, field: Field) -> str:
        """The column as a unique index wants it (MySQL needs a length for a TEXT column)."""
        return self.quote(field.name)

    def drop_index_sql(self, index: str, table: str) -> str:
        return f"DROP INDEX {self.quote(index)}"

    def rollback(self) -> None:
        connection = getattr(self, "connection", None)
        if connection is not None:
            connection.rollback()

    # -- rows -------------------------------------------------------------
    def count_rows(self, table: str, *, where: dict[str, Any] | None = None) -> int:
        check_user_table(table)
        sql = f"SELECT COUNT(*) FROM {self.quote(table)}"
        params: list[Any] = []
        if where:
            info = self.describe_table(table)
            clause, params = where_clause(self, normalise_filter(info.fields, where), fields=info.fields)
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
        params = [self._resolve(known[name], coerce(values[name], known[name].type)) for name in names]
        if not names:
            raise BadName("Give at least one field a value.")
        self._check_repeats(table, known, dict(zip(names, params)))
        sql = (
            f"INSERT INTO {self.quote(table)} "
            f"({', '.join(self.quote(n) for n in names)}) VALUES ({self.marks(len(names))})"
        )
        cursor = self._write(sql, params)
        row_id = self.last_row_id(cursor, table) if info.has_row_id else None
        self.commit()
        return row_id

    def _write(self, sql: str, params: Sequence[Any]) -> Any:
        """Run an INSERT or UPDATE; an engine's "that would repeat" comes back in words."""
        try:
            return self.execute(sql, params)
        except Exception as error:  # each driver has its own IntegrityError class
            if "integrity" in type(error).__name__.lower() or "unique" in str(error).lower():
                self.rollback()
                raise JubakoError("That would repeat a value in a field that must not repeat.") from error
            raise

    def add_rows(self, table: str, fields: Sequence[Field], rows: Sequence[Sequence[Any]]) -> int:
        """Bulk insert already-typed rows. Used by the spreadsheet import."""
        if not rows:
            return 0
        names = [f.name for f in fields]
        sql = (
            f"INSERT INTO {self.quote(table)} "
            f"({', '.join(self.quote(n) for n in names)}) VALUES ({self.marks(len(names))})"
        )
        lookups = [index for index, f in enumerate(fields) if f.type == LOOKUP]
        count = 0
        for row in rows:
            row = list(row)
            for index in lookups:
                row[index] = self._resolve(fields[index], row[index])
            self._write(sql, row)
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
        clause, params = where_clause(self, filter_spec, fields=info.fields)
        if not sort and (order_by or descending):
            sort = [{"field": order_by or ROW_ID, "descending": descending}]
        sort_spec = normalise_sort(info.fields, sort)

        columns = [ROW_ID] + [f.name for f in info.fields]
        if not info.has_row_id and any(item["field"] == ROW_ID for item in sort_spec):
            sort_spec = [item for item in sort_spec if item["field"] != ROW_ID]
        selected = [self.quote(c) for c in columns]
        if not info.has_row_id:
            selected[0] = "NULL"  # no row number to show (and no column to read it from)
        lookups = [f for f in info.fields if f.type == LOOKUP]
        selected += [lookup_text_sql(self, f, table) for f in lookups]
        order = order_clause(self, sort_spec, row_id=info.has_row_id, fields=info.fields, table=table)
        sql = (
            f"SELECT {', '.join(selected)} FROM {self.quote(table)} "
            + (f"WHERE {clause} " if clause else "")
            + (f"ORDER BY {order} " if order else "")
            + f"LIMIT {limit} OFFSET {offset}"
        )
        rows = self.query(sql, params)
        # Column 0 is the row id; the rest line up with the fields; then the words each lookup shows.
        types = [None] + [f.type for f in info.fields]
        width = len(columns)
        ids: dict[str, list[Any]] = {f.name: [] for f in lookups}
        shown_rows = []
        for row in rows:
            out = [as_field_value(value, types[index]) for index, value in enumerate(row[:width])]
            for extra, f in enumerate(lookups):
                position = columns.index(f.name)
                row_number = out[position]
                ids[f.name].append(row_number)
                words = to_jsonable(row[width + extra])
                out[position] = None if row_number is None else (words if words not in (None, "") else f"#{row_number}")
            shown_rows.append(out)
        matching = self.count_rows(table, where=filter_spec) if filter_spec else info.row_count
        return {
            "table": table,
            "fields": [field_dict(f) for f in info.fields],
            "columns": columns,
            "rows": shown_rows,
            # For each lookup field, the row numbers behind the words in "rows".
            "ids": ids,
            "limit": limit,
            "offset": offset,
            "total": matching,
            "total_all": info.row_count,
            "filter": filter_spec,
            "sort": sort_spec,
            "editable": info.has_row_id,
        }

    def update_row(self, table: str, row_id: int, values: dict[str, Any]) -> bool:
        info = self.describe_table(table)
        known = {f.name: f for f in info.fields}
        unknown = [name for name in values if name not in known]
        if unknown:
            raise BadName(f"This table has no field called {unknown[0]!r}.")
        if not info.has_row_id:
            raise JubakoError(NO_ROW_ID)
        names = list(values)
        if not names:
            return False
        params = [self._resolve(known[name], coerce(values[name], known[name].type)) for name in names]
        self._check_repeats(table, known, dict(zip(names, params)), row_id=int(row_id))
        assignments = ", ".join(
            f"{self.quote(name)} = {self.placeholder(i)}" for i, name in enumerate(names)
        )
        params.append(int(row_id))
        cursor = self._write(
            f"UPDATE {self.quote(table)} SET {assignments} "
            f"WHERE {self.quote(ROW_ID)} = {self.placeholder(len(names))}",
            params,
        )
        self.commit()
        return bool(getattr(cursor, "rowcount", 0))

    # -- many rows at once -------------------------------------------------
    def update_matching(
        self, table: str, where: dict[str, Any] | None, values: dict[str, Any], *, every_row: bool = False
    ) -> int:
        """Set fields in every row the filter finds. With no filter, `every_row` must say so.

        Returns how many rows were changed.
        """
        info = self.describe_table(table)
        known = {f.name: f for f in info.fields}
        unknown = [name for name in values if name not in known]
        if unknown:
            raise BadName(f"This table has no field called {unknown[0]!r}.")
        if not values:
            raise JubakoError("Say which field to change, and to what.")
        filter_spec = normalise_filter(info.fields, where)
        if filter_spec is None and not every_row:
            raise JubakoError("No filter is on, so this would change every row. Say so to go ahead.")
        names = list(values)
        params = []
        for name in names:
            try:
                params.append(self._resolve(known[name], coerce(values[name], known[name].type)))
            except (ValueError, TypeError):
                want = {"integer": "a whole number", "real": "a number", "date": "a date like 2024-01-31",
                        "boolean": "yes or no"}.get(known[name].type, "words")
                raise JubakoError(f"{known[name].title} needs {want}. “{values[name]}” does not fit.") from None
        matching = self.count_rows(table, where=filter_spec) if filter_spec else info.row_count
        clause, where_params = where_clause(self, filter_spec, first_index=len(names), fields=info.fields)
        unique_values = {name: value for name, value in zip(names, params) if known[name].unique and value is not None}
        if unique_values:
            if matching > 1:
                field = known[next(iter(unique_values))]
                raise JubakoError(f"{field.title} cannot repeat, so it cannot be set to one value in {matching} rows.")
            if matching == 1 and info.has_row_id:
                target = self.list_rows(table, limit=1, where=filter_spec)["rows"][0][0]
                self._check_repeats(table, known, unique_values, row_id=int(target))
        assignments = ", ".join(f"{self.quote(name)} = {self.placeholder(i)}" for i, name in enumerate(names))
        cursor = self._write(
            f"UPDATE {self.quote(table)} SET {assignments}" + (f" WHERE {clause}" if clause else ""),
            params + where_params,
        )
        self.commit()
        changed = getattr(cursor, "rowcount", -1)
        return matching if changed is None or changed < 0 else int(changed)

    def delete_matching(self, table: str, where: dict[str, Any] | None, *, every_row: bool = False) -> int:
        """Delete every row the filter finds. With no filter, `every_row` must say so. Returns how many."""
        info = self.describe_table(table)
        filter_spec = normalise_filter(info.fields, where)
        if filter_spec is None and not every_row:
            raise JubakoError("No filter is on, so this would delete every row. Say so to go ahead.")
        matching = self.count_rows(table, where=filter_spec) if filter_spec else info.row_count
        clause, params = where_clause(self, filter_spec, fields=info.fields)
        self._check_not_pointed_at(
            table, f"SELECT {self.quote(ROW_ID)} FROM {self.quote(table)}" + (f" WHERE {clause}" if clause else ""),
            params, matching,
        )
        cursor = self.execute(f"DELETE FROM {self.quote(table)}" + (f" WHERE {clause}" if clause else ""), params)
        self.commit()
        deleted = getattr(cursor, "rowcount", -1)
        return matching if deleted is None or deleted < 0 else int(deleted)

    def summarize(self, table: str, where: dict[str, Any] | None = None) -> dict[str, Any]:
        """How many rows the filter finds, and for each field: how many are filled in, and
        for numbers the total, average, lowest and highest; for dates the earliest and latest."""
        info = self.describe_table(table)
        filter_spec = normalise_filter(info.fields, where)
        clause, params = where_clause(self, filter_spec, fields=info.fields)
        tail = f" FROM {self.quote(table)}" + (f" WHERE {clause}" if clause else "")
        parts = ["COUNT(*)"]
        for field in info.fields:
            column = self.quote(field.name)
            parts.append(f"COUNT({column})")
            if field.type in ("integer", "real"):
                parts += [f"SUM({column})", f"AVG({column})", f"MIN({column})", f"MAX({column})"]
            elif field.type == "date":
                parts += [f"MIN({column})", f"MAX({column})"]
            elif field.type == "boolean":
                parts.append(f"SUM(CASE WHEN {column} THEN 1 ELSE 0 END)")
        row = self.query(f"SELECT {', '.join(parts)}{tail}", params)[0]
        values = iter(row)
        out = {"table": table, "rows": int(next(values) or 0), "filter": filter_spec, "fields": []}
        for field in info.fields:
            item: dict[str, Any] = {"name": field.name, "label": field.title, "type": field.type,
                                    "filled": int(next(values) or 0)}
            if field.type in ("integer", "real"):
                total, average, low, high = (next(values) for _ in range(4))
                item.update(total=_number(total, 10), average=_number(average, 2), lowest=_number(low, 10),
                            highest=_number(high, 10))
            elif field.type == "date":
                low, high = next(values), next(values)
                item.update(earliest=to_jsonable(low), latest=to_jsonable(high))
            elif field.type == "boolean":
                item["yes"] = int(next(values) or 0)
            out["fields"].append(item)
        return out

    def delete_row(self, table: str, row_id: int) -> bool:
        if not self.describe_table(table).has_row_id:
            raise JubakoError(NO_ROW_ID)
        self._check_not_pointed_at(table, self.placeholder(0), [int(row_id)], 1)
        cursor = self.execute(
            f"DELETE FROM {self.quote(table)} WHERE {self.quote(ROW_ID)} = {self.placeholder(0)}",
            (int(row_id),),
        )
        self.commit()
        return bool(getattr(cursor, "rowcount", 0))

    # -- lookups -----------------------------------------------------------
    def _resolve(self, field: Field, value: Any) -> Any:
        """The row number a lookup value means: a number is a row; words name the row whose shown field
        has them (case does not matter); "#12" is row 12. Anything else is refused in words."""
        if field.type != LOOKUP or value is None:
            return value
        target, shown = self.quote(field.target or ""), self.quote(field.show or "")
        if isinstance(value, str):
            text = value.strip()
            rows = self.query(
                f"SELECT {self.quote(ROW_ID)} FROM {target} WHERE LOWER(TRIM({shown})) = LOWER({self.placeholder(0)}) "
                f"LIMIT 2",
                [text],
            )
            if len(rows) == 1:
                return int(rows[0][0])
            label = self._shown_label(field)
            if rows:
                raise JubakoError(f"More than one row of {field.target} has {label} “{text}”, so {field.title} "
                                  f"cannot tell which. Give its row number instead, like #12.")
            number = text.removeprefix("#")
            if not number.isdigit():
                raise JubakoError(f"No row of {field.target} has {label} “{text}”. "
                                  f"Add it to {field.target} first, or pick one that is there.")
            value = int(number)
        rows = self.query(f"SELECT COUNT(*) FROM {target} WHERE {self.quote(ROW_ID)} = {self.placeholder(0)}", [int(value)])
        if not rows or int(rows[0][0]) == 0:
            raise JubakoError(f"{field.target} has no row {value} for {field.title} to point at.")
        return int(value)

    def _shown_label(self, field: Field) -> str:
        known = {f.name: f for f in self.remembered_fields(field.target or "") or []}
        shown = known.get(field.show or "")
        return shown.title if shown else str(field.show)

    def _check_not_pointed_at(self, table: str, ids_sql: str, params: Sequence[Any], how_many: int) -> None:
        """Refuse to delete rows that lookups still point at, saying where."""
        for src, f in self.lookups_into(table):
            rows = self.query(
                f"SELECT COUNT(*) FROM {self.quote(src)} WHERE {self.quote(f.name)} IN ({ids_sql})", list(params)
            )
            count = int(rows[0][0]) if rows else 0
            if count:
                them = "this row" if how_many == 1 else "these rows"
                plural = "row" if count == 1 else "rows"
                raise JubakoError(
                    f"{count} {plural} of {src} still point at {them} through {f.title}. "
                    f"Change or delete {'it' if count == 1 else 'them'} first."
                )

    def convert_to_lookup(
        self, table: str, name: str, target: str, show: str, *, add_missing: bool = False,
    ) -> dict[str, Any]:
        """Turn a words field into a lookup: each value becomes the row of `target` whose `show` field
        has the same words (case and spaces at the ends do not matter).

        Values that match no row are refused, naming them, unless `add_missing`, which adds them to
        `target`. Values that match two rows are always refused.
        """
        info = self.describe_table(table)
        known = {f.name: f for f in info.fields}
        if name not in known:
            raise BadName(f"The table {table!r} has no field called {name!r}.")
        field = known[name]
        if field.type == LOOKUP:
            raise JubakoError(f"{field.title} already points at rows of {field.target}.")
        if field.type != TEXT:
            raise JubakoError(f"Only a words field can become a lookup; {field.title} holds something else.")
        if target == table and show == name:
            raise JubakoError(f"{field.title} cannot show itself.")
        lookup = replace(field, type=LOOKUP, unique=False, target=target, show=show)
        self._check_lookup(table, lookup, info.fields)

        column = self.quote(name)
        values = [str(row[0]) for row in self.query(
            f"SELECT DISTINCT {column} FROM {self.quote(table)} WHERE {column} IS NOT NULL"
        ) if str(row[0]).strip()]
        by_words: dict[str, list[int]] = {}
        for row_number, words in self.query(f"SELECT {self.quote(ROW_ID)}, {self.quote(show)} FROM {self.quote(target)}"):
            if words is not None:
                by_words.setdefault(str(words).strip().lower(), []).append(int(row_number))
        label = {f.name: f for f in self.describe_table(target).fields}[show].title

        twice = sorted({v.strip() for v in values if len(by_words.get(v.strip().lower(), [])) > 1})
        if twice:
            raise JubakoError(
                f"More than one row of {target} has {label} {_listing(twice)}, so those cannot be told apart. "
                f"Make them different in {target} first."
            )
        missing = sorted({v.strip() for v in values if v.strip().lower() not in by_words}, key=str.lower)
        added: list[str] = []
        if missing:
            if not add_missing:
                raise LookupMissing(
                    f"{len(missing)} value{'s' if len(missing) != 1 else ''} of {field.title} match no row of "
                    f"{target} by {label}: {_listing(missing)}. Add them to {target}, or let Jubako add them.",
                    missing,
                )
            for words in missing:
                row_number = self.add_row(target, {show: words})
                by_words[words.lower()] = [int(row_number)]
                added.append(words)

        temporary = f"{name[:50]}_jubako_new"
        try:
            self.execute(f"ALTER TABLE {self.quote(table)} ADD COLUMN {self.column_sql(replace(lookup, name=temporary))}")
            for words in values:
                self.execute(
                    f"UPDATE {self.quote(table)} SET {self.quote(temporary)} = {self.placeholder(0)} "
                    f"WHERE {column} = {self.placeholder(1)}",
                    [by_words[words.strip().lower()][0], words],
                )
            if field.unique:
                self.execute(self.drop_index_sql(unique_index_name(table, name), table))
            self.execute(f"ALTER TABLE {self.quote(table)} DROP COLUMN {column}")
            self.execute(f"ALTER TABLE {self.quote(table)} RENAME COLUMN {self.quote(temporary)} TO {column}")
            self.remember_fields(table, [lookup if f.name == name else f for f in info.fields])
            self.commit()
        except Exception:
            self.rollback()
            raise
        return {"table": table, "field": name, "target": target, "show": show,
                "values": len(values), "added": added}


def _listing(values: Sequence[str], most: int = 5) -> str:
    shown = ", ".join(f"“{v}”" for v in values[:most])
    return shown + (f" and {len(values) - most} more" if len(values) > most else "")


def unique_index_name(table: str, field: str) -> str:
    """The name of a no-repeats index: short, safe, and the same every time for a table and field."""
    return "jubako_u_" + hashlib.sha1(f"{table}.{field}".encode()).hexdigest()[:16]


def _value_text(value: Any) -> str:
    value = to_jsonable(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _number(value: Any, digits: int | None = None) -> Any:
    """A total or average as a plain number: whole when it is whole, rounded when asked."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return to_jsonable(value)
    if digits is not None:
        number = round(number, digits)
    return int(number) if number.is_integer() else number
