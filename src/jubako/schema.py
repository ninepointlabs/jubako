"""Changing the shape of things: rename or delete a field, delete a table or a
whole database file. Each one also keeps the forms and reports remembered in
the database in step, so nothing points at a field that is gone.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .errors import JubakoError
from .paths import DB_SUFFIXES, database_path, resolve_under_roots
from .reports import FORM_KEY, REPORT_KEY, list_reports, load_form, load_report, normalise_spec
from .fields import FIELD_TYPES, Field, field_dict, slugify_name
from .filters import filter_fields, rename_in_filter
from .storage import SQLITE
from .views import forget_views, retarget_views
from .storage.base import Storage, TableInfo, to_json


def add_field(
    storage: Storage, table: str, *, label: str = "", name: str = "", field_type: str = "text",
    unique: bool = False,
) -> dict[str, Any]:
    """Add a field. The name inside comes from the label when not given. `unique`: no repeats."""
    label = (label or "").strip()
    name = (name or "").strip()
    if not label and not name:
        raise JubakoError("Give the new field a label.")
    name = name or slugify_name(label, fallback="field")
    if field_type not in FIELD_TYPES:
        raise JubakoError(f"Unknown field type {field_type!r}. Use: {', '.join(FIELD_TYPES)}.")
    info = storage.add_field(table, Field(name=name, type=field_type, label=label or None, unique=bool(unique)))
    return _field_result(info, table)


def set_unique(storage: Storage, table: str, name: str, unique: bool = True) -> dict[str, Any]:
    """Turn "no repeats" on or off for a field. Turning it on is refused while values repeat."""
    return _field_result(storage.set_unique(table, name, bool(unique)), table)


def add_row_number(storage: Storage, table: str) -> dict[str, Any]:
    """Give a table made outside Jubako an automatic row number, so its rows can be edited."""
    info = storage.add_row_number(table)
    result = _field_result(info, table)
    result["rows"] = info.row_count
    return result


def rename_field(
    storage: Storage, table: str, old: str, new: str, *, label: str | None = None
) -> dict[str, Any]:
    info = storage.rename_field(table, old, new, label=label)
    if new != old:
        _retarget(storage, table, old, new)
    return _field_result(info, table)


def relabel_field(storage: Storage, table: str, name: str, label: str) -> dict[str, Any]:
    return _field_result(storage.relabel_field(table, name, label), table)


def drop_field(storage: Storage, table: str, name: str) -> dict[str, Any]:
    info = storage.drop_field(table, name)
    _retarget(storage, table, name, None)
    return _field_result(info, table)


def drop_table(storage: Storage, table: str) -> dict[str, Any]:
    """Delete a table and its rows, and forget its form and its reports."""
    info = storage.describe_table(table)
    storage.drop_table(table)
    _forget_key(storage, FORM_KEY + table)
    views_forgotten = forget_views(storage, table)
    forgotten = []
    for report in list_reports(storage):
        if report["table"] == table:
            _forget_key(storage, REPORT_KEY + report["name"])
            forgotten.append(report["name"])
    return {"table": table, "rows_deleted": info.row_count, "reports_forgotten": forgotten,
            "views_forgotten": views_forgotten}


def delete_database_file(storage: Storage | None, path: str) -> dict[str, Any]:
    """Remove a local .jubadb file for good. Server databases are never dropped here."""
    from . import catalog  # noqa: PLC0415

    if storage is not None:
        if storage.backend != SQLITE:
            raise JubakoError(
                "Only a database file on this computer can be deleted here. "
                "A server database is left alone; ask the server's own tools."
            )
        storage.close()
    target = resolve_under_roots(path)
    if target.suffix.lower() not in DB_SUFFIXES:
        raise JubakoError(f"{target.name} is not a database file.")
    if not target.exists():
        catalog.forget(backend=SQLITE, path=str(target))
        raise JubakoError(f"There is no database at {target}.")
    removed = []
    for candidate in (target, Path(str(target) + "-wal"), Path(str(target) + "-shm"),
                      Path(str(target) + "-journal")):
        if candidate.exists():
            candidate.unlink()
            removed.append(str(candidate))
    catalog.forget(backend=SQLITE, path=str(target))
    return {"deleted": True, "file": str(target), "removed": removed}


def rename_database(storage: Storage, title: str) -> dict[str, Any]:
    """Change the database's title: the words on Home and at the top of the window."""
    title = (title or "").strip()
    if not title:
        raise JubakoError("Give the database a name.")
    if len(title) > 120:
        raise JubakoError("A database name must be 120 letters or fewer.")
    storage.set_info("title", title)
    return {"title": title, "location": storage.location()}


def save_copy(storage: Storage, path: str, *, overwrite: bool = False) -> dict[str, Any]:
    """Write a copy of a database file somewhere else, safely, even while it is open.

    The copy is a whole, working `.jubadb` (SQLite's own backup, so nothing
    half-written ends up in it). The open database stays the one in use.
    """
    if storage.backend != SQLITE:
        raise JubakoError(
            "A copy can be saved from a database file on this computer. "
            "For a server database, use the server's own backup tools."
        )
    target = database_path(path)
    if target.resolve() == Path(storage.location()).resolve():
        raise JubakoError("That is the database itself. Pick another name or folder for the copy.")
    existed = target.exists()
    if existed and not overwrite:
        raise JubakoError(f"There is already a file at {target}. Pass overwrite to replace it.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    storage.commit()
    source = storage.connection  # type: ignore[attr-defined]
    destination = sqlite3.connect(str(temporary))
    try:
        source.backup(destination)
        destination.execute("PRAGMA journal_mode = DELETE")  # one self-contained file, no -wal beside it
    finally:
        destination.close()
    temporary.replace(target)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return {"file": str(target), "bytes": target.stat().st_size, "replaced_existing_file": existed}


# -- inside -------------------------------------------------------------

def _field_result(info: TableInfo, table: str) -> dict[str, Any]:
    return {
        "table": table,
        "fields": [field_dict(f) for f in info.fields],
    }


def _retarget(storage: Storage, table: str, old: str, new: str | None) -> None:
    """Point the kept form, reports and views at the new name, or drop the old one."""
    retarget_views(storage, table, old, new)
    form = load_form(storage, table)
    if form:
        fields = [(new if n == old else n) for n in form.get("fields", []) if new or n != old]
        labels = {}
        for name, label in form.get("labels", {}).items():
            if name == old:
                if new:
                    labels[new] = label
            else:
                labels[name] = label
        form["fields"], form["labels"] = fields, labels
        form["hidden"] = [(new if n == old else n) for n in form.get("hidden", []) if new or n != old]
        storage.set_info(FORM_KEY + table, to_json(form))
    for item in list_reports(storage):
        if item["table"] != table:
            continue
        spec = load_report(storage, item["name"])
        if not spec or not _report_uses(spec, old):
            continue
        sort = list(spec.get("sort") or [])
        totals = dict(spec.get("totals") or {})
        if new:
            spec["columns"] = [(new if c == old else c) for c in spec.get("columns", [])]
            spec["filter"] = rename_in_filter(spec.get("filter"), old, new)
            spec["sort"] = [{**s, "field": new} if s.get("field") == old else s for s in sort]
            spec["group_by"] = new if spec.get("group_by") == old else spec.get("group_by", "")
            spec["totals"] = {(new if name == old else name): how for name, how in totals.items()}
        else:
            spec["columns"] = [c for c in spec.get("columns", []) if c != old]
            # Rules on a field that is gone cannot be kept; the report shows its rows unfiltered.
            if old in filter_fields(spec.get("filter")):
                spec["filter"] = None
            spec["sort"] = [s for s in sort if s.get("field") != old]
            spec["group_by"] = "" if spec.get("group_by") == old else spec.get("group_by", "")
            spec["totals"] = {name: how for name, how in totals.items() if name != old}
        if not spec["columns"]:
            _forget_key(storage, REPORT_KEY + item["name"])
            continue
        # Labels and types are re-read from the table, so they match its new shape.
        try:
            fresh = normalise_spec(storage, spec)
        except JubakoError:
            # The saved view it used went with the field.
            fresh = normalise_spec(storage, {**spec, "view": ""})
        storage.set_info(REPORT_KEY + item["name"], to_json(fresh))


def _report_uses(spec: dict[str, Any], name: str) -> bool:
    return (
        name in spec.get("columns", [])
        or name in filter_fields(spec.get("filter"))
        or any(item.get("field") == name for item in spec.get("sort") or [])
        or spec.get("group_by") == name
        or name in (spec.get("totals") or {})
    )


def _forget_key(storage: Storage, key: str) -> None:
    storage.execute(
        f"DELETE FROM {storage.quote('jubako_info')} WHERE {storage.quote('key')} = {storage.placeholder(0)}",
        (key,),
    )
    storage.commit()
