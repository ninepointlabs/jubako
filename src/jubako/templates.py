"""Templates: ready-made databases for common jobs (contacts, stock, projects...).

A template is a small JSON file next to this module: its tables and fields,
a few made-up example rows, and the saved views, reports and forms that make
it useful from the first minute. Applying one to an empty database makes all
of that; the example rows are optional.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from .errors import JubakoError
from .fields import coerce, field_from_dict
from .reports import save_form, save_report
from .storage.base import Storage
from .views import save_view

PACKAGE = "jubako.template_files"


def _files() -> list[Any]:
    return sorted(
        (entry for entry in resources.files(PACKAGE).iterdir() if entry.name.endswith(".json")),
        key=lambda entry: entry.name,
    )


def list_templates() -> list[dict[str, Any]]:
    """Every template: key, title, blurb and the tables it makes, in a steady order."""
    out = []
    for entry in _files():
        template = json.loads(entry.read_text("utf-8"))
        out.append({
            "key": template["key"],
            "title": template["title"],
            "blurb": template.get("blurb", ""),
            "tables": [table["name"] for table in template["tables"]],
            "order": template.get("order", 100),
        })
    out.sort(key=lambda item: (item["order"], item["title"]))
    for item in out:
        item.pop("order")
    return out


def load_template(key: str) -> dict[str, Any]:
    key = (key or "").strip().lower()
    for entry in _files():
        template = json.loads(entry.read_text("utf-8"))
        if template["key"] == key:
            return template
    known = ", ".join(item["key"] for item in list_templates())
    raise JubakoError(f"There is no template called {key!r}. Pick one of: {known}.")


def apply_template(storage: Storage, key: str, *, sample_rows: bool = True) -> dict[str, Any]:
    """Make a template's tables, views, reports and forms in this database.

    Refuses (before changing anything) if a table it would make is already there.
    """
    template = load_template(key)
    clashes = [table["name"] for table in template["tables"] if storage.has_table(table["name"])]
    if clashes:
        raise JubakoError(
            f"This database already has a table called {clashes[0]!r}. "
            "Start the template in a new database instead."
        )

    made = []
    rows_added = 0
    for table in template["tables"]:
        fields = [field_from_dict(f) for f in table["fields"]]
        storage.create_table(table["name"], fields)
        if sample_rows and table.get("rows"):
            typed = [
                [coerce(value, field.type) for value, field in zip(row, fields)]
                for row in table["rows"]
            ]
            rows_added += storage.add_rows(table["name"], fields, typed)
        made.append(table["name"])

    for form in template.get("forms", []):
        save_form(storage, form["table"], form)
    for view in template.get("views", []):
        # The tables are new, so a view already under this name is a leftover from a table long gone.
        save_view(storage, view["table"], view["name"], view.get("filter"),
                  sort=view.get("sort"), default=view.get("default"), replace=True)
    for report in template.get("reports", []):
        save_report(storage, report)

    return {
        "template": template["key"],
        "title": template["title"],
        "tables": made,
        "rows_added": rows_added,
        "views": [view["name"] for view in template.get("views", [])],
        "reports": [report["name"] for report in template.get("reports", [])],
    }
