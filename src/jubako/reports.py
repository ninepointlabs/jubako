"""Reports and forms: the printable list of a table, and how a form is laid out.

A *report* is a tidy, fitted table of rows: pick the table, the columns, a
title, the page size and orientation. "Fitted" means the columns shrink and
the text wraps so the whole table fits the page width, nothing clipped.

Rows can be sorted, grouped by a field (a heading per group, with how many
rows it has) and totalled: a number column can show its sum or its average,
per group and for the whole report. A report can take its rows from a saved
view by name, so it follows the view when the view changes.

This module holds the parts that need no toolkit: the spec, the row fetch,
the column-fitting arithmetic, and where forms and reports are remembered
(inside the database itself, in Jubako's own info table). Drawing the
pages needs Qt and lives in `printing.py`, which this module calls only when
a PDF is actually asked for.
"""

from __future__ import annotations

import json
from typing import Any

from .errors import BadName, JubakoError
from .fields import INTEGER, REAL
from .filters import filter_words, normalise_filter, normalise_sort, sort_words
from .paths import resolve_under_roots
from .storage.base import Storage, to_json

#: Page sizes in points (1/72 inch), portrait.
PAGE_SIZES = {
    "letter": (612.0, 792.0),
    "a4": (595.0, 842.0),
    "legal": (612.0, 1008.0),
}
ORIENTATIONS = ("portrait", "landscape")
MAX_REPORT_ROWS = 20000
CHUNK = 1000

FORM_KEY = "form:"
REPORT_KEY = "report:"

#: How a number column can be totalled.
TOTALS = ("sum", "average")
NUMBER_TYPES = {INTEGER, REAL}
MAX_TEXT = 200


# -------------------------------------------------------------------------
# Report specs
# -------------------------------------------------------------------------

def normalise_spec(storage: Storage, spec: dict[str, Any]) -> dict[str, Any]:
    """Fill in the blanks of a report spec and check it against the table."""
    table = spec.get("table") or ""
    info = storage.describe_table(table)
    known = {f.name: f for f in info.fields}

    columns = list(spec.get("columns") or [f.name for f in info.fields])
    for name in columns:
        if name not in known:
            raise BadName(f"The table {table!r} has no field called {name!r}.")
    if not columns:
        raise JubakoError("Pick at least one column for the report.")

    page_size = str(spec.get("page_size") or "letter").lower()
    if page_size not in PAGE_SIZES:
        raise JubakoError(f"Unknown page size {page_size!r}. Use: {', '.join(PAGE_SIZES)}.")
    orientation = str(spec.get("orientation") or "portrait").lower()
    if orientation not in ORIENTATIONS:
        raise JubakoError("Orientation must be portrait or landscape.")

    margins = float(spec.get("margins_mm", 15))
    margins = min(max(margins, 5.0), 40.0)
    font_pt = float(spec.get("font_pt", 10))
    font_pt = min(max(font_pt, 6.0), 16.0)

    view_name = str(spec.get("view") or "").strip()
    if view_name:
        from .views import get_view  # noqa: PLC0415 - views imports nothing from here, but keep it lazy

        view = get_view(storage, table, view_name)
        if view is None:
            raise JubakoError(f"The saved view “{view_name}” is not there any more. Pick another, or none.")
        row_filter = normalise_filter(info.fields, view.get("filter") or None)
        sort = normalise_sort(info.fields, view.get("sort") or None)
    else:
        row_filter = normalise_filter(info.fields, spec.get("filter") or None)
        sort = normalise_sort(info.fields, spec.get("sort") or None)

    group_by = str(spec.get("group_by") or "").strip()
    if group_by and group_by not in known:
        raise BadName(f"The table {table!r} has no field called {group_by!r}.")

    totals: dict[str, str] = {}
    for name, how in dict(spec.get("totals") or {}).items():
        if not how:
            continue
        how = str(how).lower()
        if how not in TOTALS:
            raise JubakoError(f"A column can show its sum or its average, not {how!r}.")
        if name not in known:
            raise BadName(f"The table {table!r} has no field called {name!r}.")
        if known[name].type not in NUMBER_TYPES:
            raise JubakoError(f"Only number columns can be totalled; {known[name].title} is not one.")
        if name in columns:
            totals[name] = how

    show_count = spec.get("show_count")
    show_count = bool(group_by) if show_count is None else bool(show_count)

    return {
        "name": str(spec.get("name") or ""),
        "table": table,
        "title": str(spec.get("title") or info.name.replace("_", " ").title()),
        "columns": columns,
        "view": view_name,
        "filter": row_filter,
        "filter_words": filter_words(info.fields, row_filter),
        "sort": sort,
        "sort_words": sort_words(info.fields, sort),
        "group_by": group_by,
        "group_label": known[group_by].title if group_by else "",
        "group_type": known[group_by].type if group_by else "",
        "totals": totals,
        "show_count": show_count,
        "header_text": str(spec.get("header_text") or "").strip()[:MAX_TEXT],
        "footer_text": str(spec.get("footer_text") or "").strip()[:MAX_TEXT],
        "labels": [known[name].title for name in columns],
        "types": [known[name].type for name in columns],
        "page_size": page_size,
        "orientation": orientation,
        "margins_mm": margins,
        "fit_to_width": bool(spec.get("fit_to_width", True)),
        "font_pt": font_pt,
        "show_row_numbers": bool(spec.get("show_row_numbers", False)),
    }


def page_points(spec: dict[str, Any]) -> tuple[float, float]:
    width, height = PAGE_SIZES[spec["page_size"]]
    if spec["orientation"] == "landscape":
        width, height = height, width
    return width, height


def report_sort(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The order rows are read in: the group field first (so groups come out together), then the sort."""
    sort = list(spec.get("sort") or [])
    group = spec.get("group_by")
    if not group:
        return sort
    first = next((item for item in sort if item["field"] == group), {"field": group, "descending": False})
    return ([first] + [item for item in sort if item["field"] != group])[:3]


def fetch_values(storage: Storage, spec: dict[str, Any]) -> tuple[list[list[Any]], list[Any]]:
    """Every row's raw values in the report's column order, and each row's group value."""
    columns = spec["columns"]
    group = spec.get("group_by") or ""
    out: list[list[Any]] = []
    groups: list[Any] = []
    offset = 0
    sort = report_sort(spec)
    while len(out) < MAX_REPORT_ROWS:
        page = storage.list_rows(spec["table"], limit=CHUNK, offset=offset, where=spec.get("filter"), sort=sort)
        if not page["rows"]:
            break
        positions = [page["columns"].index(name) for name in columns]
        group_at = page["columns"].index(group) if group else -1
        for row in page["rows"]:
            out.append([row[pos] for pos in positions])
            groups.append(row[group_at] if group else None)
        offset += CHUNK
    return out[:MAX_REPORT_ROWS], groups[:MAX_REPORT_ROWS]


def fetch_rows(storage: Storage, spec: dict[str, Any]) -> list[list[str]]:
    """Every row of the table as display text, in the report's column order."""
    types = spec["types"]
    values, _ = fetch_values(storage, spec)
    return [[cell_text(value, kind) for value, kind in zip(row, types)] for row in values]


def fetch_lines(storage: Storage, spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The report as lines to print: group headings, rows, subtotals and the grand total."""
    values, groups = fetch_values(storage, spec)
    return report_lines(spec, values, groups)


def report_lines(spec: dict[str, Any], values: list[list[Any]], groups: list[Any] | None = None) -> list[dict[str, Any]]:
    """Turn raw rows into printable lines. No toolkit, no database: easy to test.

    Lines are {"kind": "row", "cells": [...]}, {"kind": "group", "text": ..., "count": ...},
    {"kind": "subtotal" | "total", "cells": [...], "label": ...}.
    """
    columns = spec["columns"]
    types = spec["types"]
    totals = spec.get("totals") or {}
    grouped = bool(spec.get("group_by"))
    show_count = bool(spec.get("show_count"))
    groups = groups if groups is not None else [None] * len(values)

    def as_text(row: list[Any]) -> list[str]:
        return [cell_text(value, kind) for value, kind in zip(row, types)]

    def summary(rows: list[list[Any]], kind: str, label: str) -> dict[str, Any]:
        cells = []
        for index, name in enumerate(columns):
            how = totals.get(name)
            if not how:
                cells.append("")
                continue
            numbers = [row[index] for row in rows if isinstance(row[index], (int, float)) and not isinstance(row[index], bool)]
            cells.append(_total_text(numbers, how))
        return {"kind": kind, "cells": cells, "label": label}

    lines: list[dict[str, Any]] = []
    if grouped:
        start = 0
        while start < len(values):
            end = start
            while end < len(values) and _same_group(groups[end], groups[start]):
                end += 1
            members = values[start:end]
            lines.append({"kind": "group",
                          "text": f"{spec.get('group_label') or spec['group_by']}: {_group_text(groups[start], spec.get('group_type'))}",
                          "count": _rows_word(len(members)) if show_count else ""})
            lines.extend({"kind": "row", "cells": as_text(row)} for row in members)
            if totals:
                lines.append(summary(members, "subtotal", _totals_label(totals)))
            start = end
    else:
        lines.extend({"kind": "row", "cells": as_text(row)} for row in values)

    if values and (totals or show_count):
        label = "All rows" if grouped else ""
        if totals:
            label = (label + " · " if label else "") + _totals_label(totals)
        if show_count:
            label = (label + " · " if label else "") + _rows_word(len(values))
        lines.append(summary(values, "total", label))
    return lines


def _same_group(a: Any, b: Any) -> bool:
    return (a is None and b is None) or (a is not None and b is not None and a == b)


def _group_text(value: Any, kind: str | None) -> str:
    if value is None or value == "":
        return "(blank)"
    return cell_text(value, kind)


def _rows_word(count: int) -> str:
    return "1 row" if count == 1 else f"{count} rows"


def _totals_label(totals: dict[str, str]) -> str:
    kinds = set(totals.values())
    if kinds == {"sum"}:
        return "Total"
    if kinds == {"average"}:
        return "Average"
    return "Totals"


def _total_text(numbers: list[float], how: str) -> str:
    if not numbers:
        return ""
    if how == "sum":
        result = sum(numbers)
    else:
        result = sum(numbers) / len(numbers)
    if isinstance(result, float):
        result = round(result, 2)
        if result.is_integer():
            result = int(result)
    text = f"{result:,}" if isinstance(result, int) else f"{result:,.2f}".rstrip("0").rstrip(".")
    return ("avg " + text) if how == "average" else text


def cell_text(value: Any, kind: str | None) -> str:
    """How a value reads on screen and on paper: a whole number without a trailing ".0"."""
    if value is None:
        return ""
    if kind == "boolean":
        return "Yes" if value else "No"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def fit_columns(
    natural: list[float], minimum: list[float], available: float, *, fit: bool = True
) -> list[float]:
    """Choose column widths that add up to at most `available`.

    Columns that need less than their fair share keep what they need; the
    rest share what is left in proportion to how wide they wanted to be, but
    never narrower than `minimum` (roughly their longest word). If even the
    minimums do not fit, everything is scaled down together and cells wrap.
    With `fit` off, natural widths are kept and the table may run off the page.
    """
    if not natural:
        return []
    if not fit or sum(natural) <= available:
        return list(natural)

    widths = list(natural)
    fixed = [False] * len(widths)
    for _ in range(len(widths)):
        free = available - sum(w for w, f in zip(widths, fixed) if f)
        flexible = [i for i, f in enumerate(fixed) if not f]
        if not flexible:
            break
        share = free / len(flexible)
        changed = False
        for i in flexible:
            if widths[i] <= share:
                fixed[i] = True
                changed = True
        if not changed:
            total = sum(widths[i] for i in flexible)
            for i in flexible:
                widths[i] = max(minimum[i], free * widths[i] / total)
            break

    if sum(widths) > available + 0.01:
        scale = available / sum(widths)
        widths = [w * scale for w in widths]
    return widths


# -------------------------------------------------------------------------
# Exporting
# -------------------------------------------------------------------------

def export_report(
    storage: Storage, spec: dict[str, Any], file_path: str, *, overwrite: bool = False
) -> dict[str, Any]:
    """Lay the report out and write it as a PDF."""
    full = normalise_spec(storage, spec)
    target = resolve_under_roots(file_path)
    if target.suffix.lower() != ".pdf":
        target = target.with_name(target.name + ".pdf")
    existed = target.exists()
    if existed and not overwrite:
        raise JubakoError(f"There is already a file at {target}. Pass overwrite to replace it.")
    target.parent.mkdir(parents=True, exist_ok=True)

    from .printing import ReportDocument  # noqa: PLC0415 - needs Qt, only for PDF

    document = ReportDocument(full, lines=fetch_lines(storage, full))
    pages = document.write_pdf(str(target))
    return {
        "table": full["table"],
        "title": full["title"],
        "file": str(target),
        "format": "pdf",
        "rows_written": document.row_count,
        "pages": pages,
        "page_size": full["page_size"],
        "orientation": full["orientation"],
        "replaced_existing_file": existed,
    }


# -------------------------------------------------------------------------
# Remembering forms and reports inside the database
# -------------------------------------------------------------------------

def save_form(storage: Storage, table: str, form: dict[str, Any]) -> dict[str, Any]:
    """Keep a form layout for a table: field order, labels, title, and fields it hides.

    A hidden field stays out of the form; its values are kept in the table.
    Fields left out of `fields` go on the end, so every field has a place.
    """
    info = storage.describe_table(table)
    known = {f.name: f for f in info.fields}
    order = list(dict.fromkeys(form.get("fields") or [f.name for f in info.fields]))
    for name in order:
        if name not in known:
            raise BadName(f"The table {table!r} has no field called {name!r}.")
    order += [f.name for f in info.fields if f.name not in order]
    labels = dict(form.get("labels") or {})
    for name in labels:
        if name not in known:
            raise BadName(f"The table {table!r} has no field called {name!r}.")
    hidden = [name for name in dict.fromkeys(form.get("hidden") or [])]
    for name in hidden:
        if name not in known:
            raise BadName(f"The table {table!r} has no field called {name!r}.")
    if len(hidden) >= len(order):
        raise JubakoError("A form needs at least one field to show.")
    saved = {
        "table": table,
        "title": str(form.get("title") or info.name.replace("_", " ").title()).strip()[:MAX_TEXT],
        "fields": order,
        "labels": {name: str(labels.get(name) or known[name].title).strip() or known[name].title for name in order},
        "hidden": hidden,
    }
    storage.set_info(FORM_KEY + table, to_json(saved))
    return saved


def load_form(storage: Storage, table: str) -> dict[str, Any] | None:
    raw = storage.get_info(FORM_KEY + table, "")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def form_for(storage: Storage, table: str) -> dict[str, Any]:
    """The saved form, or the plain default: every field, in table order.

    `fields` is what the form shows, in order; `order` is every field's
    place (hidden ones too); `hidden` is what it leaves out.
    """
    saved = load_form(storage, table)
    info = storage.describe_table(table)
    known = {f.name: f for f in info.fields}
    if saved:
        # Fields added since the form was saved go on the end; removed ones drop out.
        order = [n for n in saved.get("fields", []) if n in known]
        order += [f.name for f in info.fields if f.name not in order]
        hidden = [n for n in saved.get("hidden", []) if n in known]
        labels = {n: saved.get("labels", {}).get(n) or known[n].title for n in order}
        shown = [n for n in order if n not in hidden] or order
        return {"table": table, "title": saved.get("title") or info.name, "fields": shown,
                "order": order, "hidden": [n for n in hidden if n not in shown], "labels": labels, "saved": True}
    return {
        "table": table,
        "title": info.name.replace("_", " ").title(),
        "fields": [f.name for f in info.fields],
        "order": [f.name for f in info.fields],
        "hidden": [],
        "labels": {f.name: f.title for f in info.fields},
        "saved": False,
    }


def reset_form(storage: Storage, table: str) -> bool:
    """Forget a table's saved form: it goes back to every field, in table order."""
    if load_form(storage, table) is None:
        return False
    storage.execute(
        f"DELETE FROM {storage.quote('jubako_info')} WHERE {storage.quote('key')} = {storage.placeholder(0)}",
        (FORM_KEY + table,),
    )
    storage.commit()
    return True


def save_report(storage: Storage, spec: dict[str, Any]) -> dict[str, Any]:
    full = normalise_spec(storage, spec)
    name = full["name"] or full["title"]
    if not name.strip():
        raise JubakoError("Give the report a name.")
    full["name"] = name.strip()
    storage.set_info(REPORT_KEY + full["name"], to_json(full))
    return full


def load_report(storage: Storage, name: str) -> dict[str, Any] | None:
    raw = storage.get_info(REPORT_KEY + name, "")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def list_reports(storage: Storage) -> list[dict[str, Any]]:
    rows = storage.query(
        f"SELECT {storage.quote('key')}, {storage.quote('value')} FROM {storage.quote('jubako_info')}"
    )
    out = []
    for key, value in rows:
        if str(key).startswith(REPORT_KEY):
            try:
                spec = json.loads(value)
            except ValueError:
                continue
            out.append({"name": spec.get("name") or str(key)[len(REPORT_KEY):],
                        "table": spec.get("table", ""), "title": spec.get("title", "")})
    return sorted(out, key=lambda item: item["name"].lower())


def follow_view(storage: Storage, table: str, old: str, new: str | None, view: dict[str, Any] | None = None) -> list[str]:
    """A saved view was renamed (`new`) or deleted: reports that used it follow, or keep its rules.

    A report whose view is deleted keeps printing the same rows: the view's
    filter and sort are copied into the report itself.
    """
    touched = []
    for item in list_reports(storage):
        if item["table"] != table:
            continue
        spec = load_report(storage, item["name"])
        if not spec or spec.get("view") != old:
            continue
        if new:
            spec["view"] = new
        else:
            spec["view"] = ""
            spec["filter"] = (view or {}).get("filter")
            spec["sort"] = (view or {}).get("sort") or []
        storage.set_info(REPORT_KEY + spec["name"], to_json(spec))
        touched.append(spec["name"])
    return touched


def delete_report(storage: Storage, name: str) -> bool:
    if load_report(storage, name) is None:
        return False
    storage.execute(
        f"DELETE FROM {storage.quote('jubako_info')} WHERE {storage.quote('key')} = {storage.placeholder(0)}",
        (REPORT_KEY + name,),
    )
    storage.commit()
    return True
