"""Saved views: a named "Show rows where…" that lives in the database file.

A view is one table, one name, a filter and/or a sort (see `filters.py`). It is kept in
Jubako's own info table under `view:<table>:<name>`, so it travels with
the `.jubadb`. One view per table may be the default: the one the table
opens with.
"""

from __future__ import annotations

import json
from typing import Any

from .errors import JubakoError
from .filters import (
    filter_fields,
    filter_words,
    normalise_filter,
    normalise_sort,
    rename_in_filter,
    sort_words,
)
from .storage.base import Storage, to_json

VIEW_KEY = "view:"


def _key(table: str, name: str) -> str:
    return f"{VIEW_KEY}{table}:{name}"


def save_view(
    storage: Storage,
    table: str,
    name: str,
    filter_spec: dict[str, Any] | None,
    *,
    replace: bool = False,
    default: bool | None = None,
    sort: Any = None,
) -> dict[str, Any]:
    """Keep a filter (and/or a sort) under a name. Refuses a blank name, and a taken one unless `replace`."""
    name = (name or "").strip()
    if not name:
        raise JubakoError("Give the view a name, like “Still here”.")
    if ":" in name or len(name) > 60:
        raise JubakoError("A view's name cannot contain a colon, and must be 60 letters or fewer.")
    info = storage.describe_table(table)
    spec = normalise_filter(info.fields, filter_spec)
    order = normalise_sort(info.fields, sort)
    if spec is None and not order:
        raise JubakoError("Apply a filter or a sort first, then save it as a view.")
    existing = get_view(storage, table, name)
    if existing and not replace:
        raise JubakoError(f"There is already a view called “{name}” for {table}. Pick another name, or replace it.")
    if default is None:
        default = bool(existing and existing.get("default"))
    if default:
        for other in list_views(storage, table):
            if other["name"] != name and other.get("default"):
                _write(storage, {**other, "default": False})
    view = {"name": name, "table": table, "filter": spec, "sort": order, "default": bool(default),
            "words": view_words(info.fields, spec, order)}
    _write(storage, view)
    view["replaced"] = bool(existing)
    return view


def get_view(storage: Storage, table: str, name: str) -> dict[str, Any] | None:
    raw = storage.get_info(_key(table, (name or "").strip()), "")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def list_views(storage: Storage, table: str | None = None) -> list[dict[str, Any]]:
    rows = storage.query(
        f"SELECT {storage.quote('key')}, {storage.quote('value')} FROM {storage.quote('jubako_info')}"
    )
    out = []
    for key, value in rows:
        key = str(key)
        if not key.startswith(VIEW_KEY):
            continue
        try:
            view = json.loads(value)
        except ValueError:
            continue
        if table and view.get("table") != table:
            continue
        out.append(view)
    return sorted(out, key=lambda v: (v.get("table", ""), v.get("name", "").lower()))


def default_view(storage: Storage, table: str) -> dict[str, Any] | None:
    for view in list_views(storage, table):
        if view.get("default"):
            return view
    return None


def delete_view(storage: Storage, table: str, name: str) -> bool:
    view = get_view(storage, table, name)
    if view is None:
        return False
    _forget(storage, _key(table, (name or "").strip()))
    from .reports import follow_view  # noqa: PLC0415 - reports reads views too

    follow_view(storage, table, view["name"], None, view)
    return True


def rename_view(storage: Storage, table: str, old: str, new: str) -> dict[str, Any]:
    view = get_view(storage, table, old)
    if view is None:
        raise JubakoError(f"There is no view called “{old}” for {table}.")
    new = (new or "").strip()
    if not new:
        raise JubakoError("Give the view a name.")
    if new != old and get_view(storage, table, new):
        raise JubakoError(f"There is already a view called “{new}” for {table}.")
    _forget(storage, _key(table, old))
    view["name"] = new
    _write(storage, view)
    from .reports import follow_view  # noqa: PLC0415 - reports reads views too

    follow_view(storage, table, old, new)
    return view


def view_words(fields: list, filter_spec: dict[str, Any] | None, sort: list[dict[str, Any]] | None) -> str:
    """A view in words: "Moved is not Yes · sorted by Age, highest first"."""
    parts = []
    if filter_spec:
        parts.append(filter_words(fields, filter_spec))
    if sort:
        parts.append("sorted by " + sort_words(fields, sort))
    return " · ".join(parts)


def retarget_views(storage: Storage, table: str, old: str, new: str | None) -> list[str]:
    """A field was renamed (`new`) or dropped (`new` None): fix or forget the views on it.

    A dropped field takes with it every view whose rules look at it (dropping
    just that rule would quietly show more rows than the view promised); a
    view that only sorted by it keeps its rules and loses that sort.
    """
    touched = []
    for view in list_views(storage, table):
        spec = view.get("filter") or None
        order = list(view.get("sort") or [])
        in_filter = old in filter_fields(spec)
        in_sort = any(item.get("field") == old for item in order)
        if not in_filter and not in_sort:
            continue
        if new:
            view["filter"] = rename_in_filter(spec, old, new)
            view["sort"] = [{**item, "field": new} if item.get("field") == old else item for item in order]
        elif in_filter:
            _forget(storage, _key(table, view["name"]))
            touched.append(view["name"])
            continue
        else:
            view["sort"] = [item for item in order if item.get("field") != old]
            if not view["filter"] and not view["sort"]:
                _forget(storage, _key(table, view["name"]))
                touched.append(view["name"])
                continue
        try:
            fields = storage.describe_table(table).fields
            view["words"] = view_words(fields, normalise_filter(fields, view["filter"]),
                                       normalise_sort(fields, view["sort"]))
        except JubakoError:
            pass
        _write(storage, view)
        touched.append(view["name"])
    return touched


def forget_views(storage: Storage, table: str) -> list[str]:
    names = []
    for view in list_views(storage, table):
        _forget(storage, _key(table, view["name"]))
        names.append(view["name"])
    return names


def _write(storage: Storage, view: dict[str, Any]) -> None:
    storage.set_info(_key(view["table"], view["name"]), to_json(view))


def _forget(storage: Storage, key: str) -> None:
    storage.execute(
        f"DELETE FROM {storage.quote('jubako_info')} WHERE {storage.quote('key')} = {storage.placeholder(0)}",
        (key,),
    )
    storage.commit()
