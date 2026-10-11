"""The Jubako MCP server.

Agents (Claude Code, and anything else that speaks MCP) attach to this over
stdio and get the same jobs the app does: make a database, import a
spreadsheet (CSV or Excel), list tables, read and change rows, keep a form
and a report, and write CSV, Excel or PDF.

It speaks MCP's JSON-RPC 2.0 framing directly over stdin/stdout, with no
third-party SDK, so the only thing needed to run it is Python.

Safety rules, enforced here and in `jubako.paths`:

- Every file path is resolved and must land inside an approved root
  (the user's home by default, or `JUBAKO_ROOTS`). Traversal is refused.
- Spreadsheet cells are read as data. In a CSV a formula is stored as its own
  text; in an Excel file the value Excel last saved is used. Nothing is ever
  worked out or run.
- Anything that would replace a file or a table says so in its result, and
  will not do it unless asked with `overwrite` / `if_exists`.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

from jubako import __version__, catalog
from jubako.errors import JubakoError
from jubako.exporter import export_table
from jubako.fields import ALL_FIELD_TYPES, field_dict
from jubako import schema, templates, views
from jubako.importer import import_spreadsheet, import_workbook, plan_import
from jubako.reports import (
    delete_report,
    export_report,
    form_for,
    list_reports,
    load_report,
    save_form,
    save_report,
)
from jubako.storage import BACKENDS, Storage, create_database, open_database

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "jubako"

_BACKEND_ENUM = [choice.key for choice in BACKENDS]

_CONNECTION_SCHEMA = {
    "type": "object",
    "description": "Server details. Only for the postgres and mysql backends.",
    "properties": {
        "host": {"type": "string"},
        "port": {"type": "integer"},
        "database": {"type": "string"},
        "user": {"type": "string"},
        "password": {"type": "string"},
        "url": {"type": "string", "description": "PostgreSQL only: a full connection URL."},
    },
    "additionalProperties": False,
}

_OPS = ["is", "is_not", "empty", "not_empty", "contains", "starts_with",
        "more_than", "less_than", "at_least", "at_most"]

_RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "field": {"type": "string"},
        "op": {"type": "string", "enum": _OPS},
        "value": {},
    },
    "required": ["field", "op"],
    "additionalProperties": False,
}

_FILTER_SCHEMA = {
    "type": "object",
    "description": (
        "Show only rows that match. Either one rule {field, op, value}, or several: "
        "{match: 'all' | 'any', rules: [{field, op, value}, ...]} (at most 10). op is one of "
        "is, is_not, empty, not_empty, contains, starts_with (those two: words fields only), "
        "more_than, less_than, at_least, at_most (numbers and dates; for a date more_than means "
        "after). Yes/no fields accept yes/no/true/false/1/0. 'is_not' keeps blank rows."
    ),
    "properties": {
        "field": {"type": "string"},
        "op": {"type": "string", "enum": _OPS},
        "value": {},
        "match": {"type": "string", "enum": ["all", "any"]},
        "rules": {"type": "array", "items": _RULE_SCHEMA, "maxItems": 10},
    },
    "additionalProperties": False,
}

_SORT_SCHEMA = {
    "type": "array",
    "description": "Sort by up to three fields, in order. Blanks always go last.",
    "items": {
        "type": "object",
        "properties": {"field": {"type": "string"}, "descending": {"type": "boolean", "default": False}},
        "required": ["field"],
        "additionalProperties": False,
    },
    "maxItems": 3,
}

#: Report settings beyond the page: which rows, their order, groups and totals.
_REPORT_ROW_PROPERTIES = {
    "sort": _SORT_SCHEMA,
    "group_by": {"type": "string", "description": "A field: rows are grouped by it, with a heading per group."},
    "totals": {
        "type": "object",
        "description": "Number columns to total: {field: 'sum' | 'average'}. Per group and for the whole report.",
        "additionalProperties": {"type": "string", "enum": ["sum", "average"]},
    },
    "show_count": {"type": "boolean", "description": "Say how many rows (per group and overall). Default: on when grouping."},
    "header_text": {"type": "string", "description": "A small line at the top of every page."},
    "footer_text": {"type": "string", "description": "Replaces the title at the foot of every page."},
    "view": {"type": "string", "description": "A saved view's name: its filter and sort choose the rows (overrides filter and sort)."},
}

_TARGET_PROPERTIES = {
    "backend": {"type": "string", "enum": _BACKEND_ENUM, "default": "sqlite"},
    "path": {"type": "string", "description": "The database file, for the sqlite backend."},
    "connection": _CONNECTION_SCHEMA,
}


def _open(arguments: dict[str, Any]) -> Storage:
    return open_database(
        backend=arguments.get("backend", "sqlite"),
        path=arguments.get("path"),
        connection=arguments.get("connection"),
    )


def _remember(storage: Storage) -> None:
    info = storage.describe()
    catalog.remember(
        title=info.title,
        backend=info.backend,
        path=info.location if info.backend == "sqlite" else "",
        where="" if info.backend == "sqlite" else info.location,
    )


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------

def tool_create_database(arguments: dict[str, Any]) -> dict[str, Any]:
    if arguments.get("template"):
        templates.load_template(arguments["template"])  # an unknown key stops here, before anything is made
    with create_database(
        title=arguments.get("title", ""),
        backend=arguments.get("backend", "sqlite"),
        path=arguments.get("path"),
        overwrite=bool(arguments.get("overwrite", False)),
        connection=arguments.get("connection"),
    ) as storage:
        made = None
        if arguments.get("template"):
            made = templates.apply_template(storage, arguments["template"],
                                            sample_rows=bool(arguments.get("sample_rows", True)))
        _remember(storage)
        info = storage.describe()
    result = {
        "made": True,
        "title": info.title,
        "backend": info.backend,
        "location": info.location,
        "replaced_existing": bool(arguments.get("overwrite", False)),
        "note": "A brand new database. It has no tables yet.",
    }
    if made:
        result["template"] = made
        result["note"] = f"Made from the {made['title']} template: tables {', '.join(made['tables'])}."
    return result


def tool_rename_database(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        result = schema.rename_database(storage, arguments["title"])
        _remember(storage)
    return result


def tool_copy_database(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        result = schema.save_copy(storage, arguments["file"], overwrite=bool(arguments.get("overwrite", False)))
    if result["replaced_existing_file"]:
        result["note"] = "A file was already there and has been replaced."
    return result


def tool_list_templates(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"templates": templates.list_templates()}


def tool_list_databases(arguments: dict[str, Any]) -> dict[str, Any]:
    entries = catalog.recent(int(arguments.get("limit", 20)))
    return {"databases": entries, "count": len(entries)}


def tool_open_database(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        info = storage.describe()
        _remember(storage)
    return {
        "opened": True,
        "title": info.title,
        "backend": info.backend,
        "location": info.location,
        "tables": info.tables,
    }


def tool_plan_import(arguments: dict[str, Any]) -> dict[str, Any]:
    return plan_import(arguments["file"], sheet=arguments.get("sheet"))


def tool_import_spreadsheet(arguments: dict[str, Any]) -> dict[str, Any]:
    if_exists = arguments.get("if_exists", "error")
    if if_exists not in ("error", "skip", "replace"):
        raise JubakoError("if_exists must be 'error', 'skip' or 'replace'.")
    with _open(arguments) as storage:
        if arguments.get("all_sheets") or arguments.get("sheet") == "*":
            result = import_workbook(storage, arguments["file"], if_exists=if_exists)
        else:
            result = import_spreadsheet(
                storage,
                arguments["file"],
                table=arguments.get("table"),
                if_exists=if_exists,
                sheet=arguments.get("sheet"),
            )
        _remember(storage)
    if if_exists == "replace":
        result["note"] = "Any table of that name was dropped first."
    return result


def tool_list_views(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        return {"views": views.list_views(storage, arguments.get("table"))}


def tool_get_view(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        view = views.get_view(storage, arguments["table"], arguments["name"])
    if view is None:
        raise JubakoError(f"There is no view called {arguments['name']!r} for {arguments['table']!r}.")
    return view


def tool_save_view(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        view = views.save_view(
            storage, arguments["table"], arguments["name"], arguments.get("filter"),
            replace=bool(arguments.get("replace", False)), default=arguments.get("default"),
            sort=arguments.get("sort"),
        )
    view["saved"] = True
    if view.get("replaced"):
        view["note"] = "A view of that name was already there and has been replaced."
    return view


def tool_delete_view(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        gone = views.delete_view(storage, arguments["table"], arguments["name"])
    return {"deleted": bool(gone), "name": arguments["name"], "table": arguments["table"],
            "note": "The rows stay; only the saved filter is gone." if gone else "No view has that name."}


def tool_rename_field(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        new = arguments.get("new_name") or arguments["field"]
        return schema.rename_field(
            storage, arguments["table"], arguments["field"], new, label=arguments.get("label")
        )


def tool_delete_field(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        result = schema.drop_field(storage, arguments["table"], arguments["field"])
    result["deleted"] = arguments["field"]
    result["note"] = "Everything that was in that field is gone."
    return result


def tool_delete_table(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        result = schema.drop_table(storage, arguments["table"])
    result["deleted"] = True
    result["note"] = f"The table and its {result['rows_deleted']} rows are gone."
    return result


def tool_delete_database(arguments: dict[str, Any]) -> dict[str, Any]:
    if not arguments.get("confirm"):
        raise JubakoError("Deleting a database cannot be undone. Call again with confirm: true.")
    if arguments.get("backend", "sqlite") != "sqlite":
        raise JubakoError(
            "Only a database file on this computer can be deleted here. "
            "A server database is left alone; ask the server's own tools."
        )
    storage = _open(arguments)
    return schema.delete_database_file(storage, arguments["path"])


def tool_list_tables(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        names = storage.list_tables()
        tables = []
        for name in names:
            info = storage.describe_table(name)
            tables.append({"name": name, "fields": len(info.fields), "rows": info.row_count})
    return {"tables": tables, "count": len(tables)}


def tool_describe_table(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        info = storage.describe_table(arguments["table"])
    result = {
        "table": info.name,
        "rows": info.row_count,
        "fields": [field_dict(f) for f in info.fields],
        "field_types": list(ALL_FIELD_TYPES),
    }
    if not info.has_row_id:
        result["editable"] = False
        result["note"] = "Made outside Jubako with no row number: rows can be read, not updated or deleted. Use add_row_number."
    return result


def tool_list_rows(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        return storage.list_rows(
            arguments["table"],
            limit=int(arguments.get("limit", 100)),
            offset=int(arguments.get("offset", 0)),
            order_by=arguments.get("order_by"),
            descending=bool(arguments.get("descending", False)),
            where=arguments.get("filter"),
            sort=arguments.get("sort"),
        )


def tool_add_field(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        result = schema.add_field(
            storage, arguments["table"], label=arguments.get("label", ""),
            name=arguments.get("name", ""), field_type=arguments.get("type", "text"),
            unique=bool(arguments.get("unique", False)),
            target=arguments.get("target", ""), show=arguments.get("show", ""),
        )
    result["added"] = result["fields"][-1]["name"]
    result["note"] = "Rows already there have nothing in the new field."
    return result


def tool_make_lookup(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        result = schema.make_lookup(
            storage, arguments["table"], arguments["field"], arguments["target"], arguments["show"],
            add_missing=bool(arguments.get("add_missing", False)),
        )
    result["note"] = (f"{arguments['field']} now keeps the row number of a row of {arguments['target']} and shows its "
                      f"{arguments['show']}. Writes may give the words or the row number.")
    return result


def tool_set_unique(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        result = schema.set_unique(storage, arguments["table"], arguments["field"], bool(arguments.get("unique", True)))
    result["note"] = ("Blank values may still repeat." if arguments.get("unique", True)
                      else "Values in this field may repeat again.")
    return result


def tool_update_rows(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        changed = storage.update_matching(
            arguments["table"], arguments.get("filter"), dict(arguments.get("values") or {}),
            every_row=bool(arguments.get("every_row", False)),
        )
    return {"updated": changed, "table": arguments["table"]}


def tool_delete_rows(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        deleted = storage.delete_matching(
            arguments["table"], arguments.get("filter"), every_row=bool(arguments.get("every_row", False)),
        )
    return {"deleted": deleted, "table": arguments["table"], "note": "This cannot be undone."}


def tool_summarize_rows(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        return storage.summarize(arguments["table"], arguments.get("filter"))


def tool_add_row_number(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        return schema.add_row_number(storage, arguments["table"])


def tool_add_row(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        row_id = storage.add_row(arguments["table"], dict(arguments.get("values") or {}))
    return {"added": True, "table": arguments["table"], "id": row_id}


def tool_update_row(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        changed = storage.update_row(
            arguments["table"], int(arguments["id"]), dict(arguments.get("values") or {})
        )
    return {"updated": bool(changed), "table": arguments["table"], "id": int(arguments["id"]),
            "note": "" if changed else "No row has that id."}


def tool_delete_row(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        gone = storage.delete_row(arguments["table"], int(arguments["id"]))
    return {"deleted": bool(gone), "table": arguments["table"], "id": int(arguments["id"]),
            "note": "" if gone else "No row has that id."}


def tool_create_form(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        form = save_form(
            storage,
            arguments["table"],
            {"title": arguments.get("title"), "fields": arguments.get("fields"),
             "labels": arguments.get("labels"), "hidden": arguments.get("hidden")},
        )
    return {"saved": True, "form": form}


def tool_get_form(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        return form_for(storage, arguments["table"])


def _report_spec(arguments: dict[str, Any]) -> dict[str, Any]:
    keys = ("name", "table", "title", "columns", "page_size", "orientation", "margins_mm",
            "fit_to_width", "font_pt", "show_row_numbers", "filter", "sort", "group_by", "totals",
            "show_count", "header_text", "footer_text", "view")
    return {key: arguments[key] for key in keys if key in arguments}


def tool_create_report(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        spec = save_report(storage, _report_spec(arguments))
    return {"saved": True, "report": spec}


def tool_list_reports(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        return {"reports": list_reports(storage)}


def tool_delete_report(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        gone = delete_report(storage, arguments["name"])
    return {"deleted": bool(gone), "name": arguments["name"]}


def tool_export_report(arguments: dict[str, Any]) -> dict[str, Any]:
    """Write a PDF from a saved report (by name) or from a spec given right here."""
    with _open(arguments) as storage:
        spec = _report_spec(arguments)
        if arguments.get("name") and not arguments.get("table"):
            saved = load_report(storage, arguments["name"])
            if saved is None:
                raise JubakoError(f"There is no report called {arguments['name']!r}.")
            spec = {**saved, **{k: v for k, v in spec.items() if k != "name"}}
        result = export_report(
            storage, spec, arguments["file"], overwrite=bool(arguments.get("overwrite", False))
        )
    if result["replaced_existing_file"]:
        result["note"] = "A file was already there and has been replaced."
    return result


def tool_export_table(arguments: dict[str, Any]) -> dict[str, Any]:
    with _open(arguments) as storage:
        result = export_table(
            storage,
            arguments["table"],
            arguments["file"],
            file_format=arguments.get("format", "csv"),
            overwrite=bool(arguments.get("overwrite", False)),
            include_id=bool(arguments.get("include_id", False)),
        )
    if result["replaced_existing_file"]:
        result["note"] = "A file was already there and has been replaced."
    return result


def tool_list_backends(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "backends": [
            {
                "key": choice.key,
                "title": choice.title,
                "what_it_is": choice.blurb,
                "needs_server": choice.needs_server,
                "driver_installed": choice.driver_installed(),
                "driver_package": choice.driver_package,
            }
            for choice in BACKENDS
        ],
        "default": "sqlite",
    }


TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_backends",
        "description": "Show the kinds of database Jubako can make, and whether each driver is installed.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": tool_list_backends,
    },
    {
        "name": "create_database",
        "description": (
            "Make a new database: empty, or from a template (see list_templates). Default backend is "
            "sqlite, which is one file on disk; give `path`. For postgres or mysql give `connection` "
            "instead — the server and its database must already exist."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "What to call it, in plain words."},
                **_TARGET_PROPERTIES,
                "template": {"type": "string", "description": "A template key, like 'contacts' or 'inventory'."},
                "sample_rows": {"type": "boolean", "default": True, "description": "With a template: put in its example rows."},
                "overwrite": {
                    "type": "boolean",
                    "default": False,
                    "description": "Replace a database that is already there. Destroys its data.",
                },
            },
            "additionalProperties": False,
        },
        "handler": tool_create_database,
    },
    {
        "name": "rename_database",
        "description": "Change a database's title (what Home and the window show). The file name stays.",
        "inputSchema": {
            "type": "object",
            "properties": {**_TARGET_PROPERTIES, "title": {"type": "string"}},
            "required": ["title"],
            "additionalProperties": False,
        },
        "handler": tool_rename_database,
    },
    {
        "name": "copy_database",
        "description": (
            "Save a copy of a database file to another file (a whole, working .jubadb; safe while it is open). "
            "Database files only, not servers. Says whether a file was replaced."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_TARGET_PROPERTIES,
                "file": {"type": "string", "description": "Where the copy goes."},
                "overwrite": {"type": "boolean", "default": False},
            },
            "required": ["file"],
            "additionalProperties": False,
        },
        "handler": tool_copy_database,
    },
    {
        "name": "list_templates",
        "description": "Ready-made databases (contacts, inventory, projects, ...) to start from with create_database.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": tool_list_templates,
    },
    {
        "name": "list_databases",
        "description": "List the databases this user has made or opened recently. Never includes passwords.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 20}},
            "additionalProperties": False,
        },
        "handler": tool_list_databases,
    },
    {
        "name": "open_database",
        "description": "Open a database and report its title and tables.",
        "inputSchema": {
            "type": "object",
            "properties": dict(_TARGET_PROPERTIES),
            "additionalProperties": False,
        },
        "handler": tool_open_database,
    },
    {
        "name": "plan_import",
        "description": (
            "Look at a CSV file and report the table, fields and guessed types it would create, "
            "without changing anything."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"file": {"type": "string"}},
            "required": ["file"],
            "additionalProperties": False,
        },
        "handler": tool_plan_import,
    },
    {
        "name": "import_spreadsheet",
        "description": (
            "Read a CSV or Excel (.xlsx) file into a new table, guessing each field's type "
            "(text, integer, real, date, boolean). One sheet per call; plan_import lists the sheets."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_TARGET_PROPERTIES,
                "file": {"type": "string", "description": "The CSV or .xlsx file to read."},
                "sheet": {"type": "string", "description": "Excel only: which sheet. Defaults to the first. '*' means every sheet."},
                "all_sheets": {"type": "boolean", "default": False, "description": "Excel only: every sheet becomes its own table, named after the sheet, with guessed types. The result lists tables and errors."},
                "table": {"type": "string", "description": "Table name. Defaults to the file (or sheet) name. Ignored with all_sheets."},
                "if_exists": {
                    "type": "string",
                    "enum": ["error", "skip", "replace"],
                    "default": "error",
                    "description": "'replace' drops a table of that name first, losing its rows.",
                },
                "sheet": {"type": "string", "description": "Excel only: which sheet to look at."},
            },
            "required": ["file"],
            "additionalProperties": False,
        },
        "handler": tool_import_spreadsheet,
    },
    {
        "name": "list_tables",
        "description": "List the tables in a database, with how many fields and rows each has.",
        "inputSchema": {
            "type": "object",
            "properties": dict(_TARGET_PROPERTIES),
            "additionalProperties": False,
        },
        "handler": tool_list_tables,
    },
    {
        "name": "describe_table",
        "description": "Show one table's fields, their types and labels, and its row count.",
        "inputSchema": {
            "type": "object",
            "properties": {**_TARGET_PROPERTIES, "table": {"type": "string"}},
            "required": ["table"],
            "additionalProperties": False,
        },
        "handler": tool_describe_table,
    },
    {
        "name": "list_rows",
        "description": "Read rows from a table, a page at a time. A lookup field shows the words of the row it points at; its row numbers are in `ids`.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_TARGET_PROPERTIES,
                "table": {"type": "string"},
                "limit": {"type": "integer", "default": 100, "maximum": 5000},
                "offset": {"type": "integer", "default": 0},
                "order_by": {"type": "string", "description": "A field name, or 'id'. Or use sort."},
                "descending": {"type": "boolean", "default": False},
                "sort": _SORT_SCHEMA,
                "filter": _FILTER_SCHEMA,
            },
            "required": ["table"],
            "additionalProperties": False,
        },
        "handler": tool_list_rows,
    },
    {
        "name": "add_row",
        "description": "Add one row to a table. Values are checked against each field's type. A lookup takes the words its row shows (like a customer's name) or the row number.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_TARGET_PROPERTIES,
                "table": {"type": "string"},
                "values": {"type": "object", "description": "Field name to value."},
            },
            "required": ["table", "values"],
            "additionalProperties": False,
        },
        "handler": tool_add_row,
    },
    {
        "name": "export_table",
        "description": (
            "Write a whole table out as CSV, Excel (.xlsx) or a fitted PDF list. Says in its "
            "result whether a file was replaced. For a PDF with chosen columns or a title, use export_report."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_TARGET_PROPERTIES,
                "table": {"type": "string"},
                "file": {"type": "string", "description": "Where to write it."},
                "format": {"type": "string", "enum": ["csv", "xlsx", "pdf"], "default": "csv"},
                "overwrite": {"type": "boolean", "default": False},
                "include_id": {"type": "boolean", "default": False},
            },
            "required": ["table", "file"],
            "additionalProperties": False,
        },
        "handler": tool_export_table,
    },
    {
        "name": "update_row",
        "description": "Change some fields of one row, found by its id. A lookup takes the words its row shows or the row number.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_TARGET_PROPERTIES,
                "table": {"type": "string"},
                "id": {"type": "integer"},
                "values": {"type": "object", "description": "Field name to new value."},
            },
            "required": ["table", "id", "values"],
            "additionalProperties": False,
        },
        "handler": tool_update_row,
    },
    {
        "name": "delete_row",
        "description": "Delete one row, found by its id. This cannot be undone.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_TARGET_PROPERTIES,
                "table": {"type": "string"},
                "id": {"type": "integer"},
            },
            "required": ["table", "id"],
            "additionalProperties": False,
        },
        "handler": tool_delete_row,
    },
    {
        "name": "create_form",
        "description": (
            "Keep a form for a table: which fields, in what order, with what labels, and which it hides. "
            "The app's form view uses it. Fields left out of `fields` still show, after the chosen ones; "
            "put a field in `hidden` to keep it off the form (its values stay in the table)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_TARGET_PROPERTIES,
                "table": {"type": "string"},
                "title": {"type": "string"},
                "fields": {"type": "array", "items": {"type": "string"}, "description": "Field names in order."},
                "labels": {"type": "object", "description": "Field name to the label people see."},
                "hidden": {"type": "array", "items": {"type": "string"}, "description": "Fields the form leaves out."},
            },
            "required": ["table"],
            "additionalProperties": False,
        },
        "handler": tool_create_form,
    },
    {
        "name": "get_form",
        "description": "The form for a table: the saved one, or the plain default.",
        "inputSchema": {
            "type": "object",
            "properties": {**_TARGET_PROPERTIES, "table": {"type": "string"}},
            "required": ["table"],
            "additionalProperties": False,
        },
        "handler": tool_get_form,
    },
    {
        "name": "create_report",
        "description": (
            "Keep a printable report: a table, its columns, a title, page size and orientation. "
            "Columns shrink and wrap to fit the page width. Export it with export_report."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_TARGET_PROPERTIES,
                "name": {"type": "string", "description": "What to call the report. Defaults to the title."},
                "table": {"type": "string"},
                "title": {"type": "string", "description": "Printed at the top of page one."},
                "columns": {"type": "array", "items": {"type": "string"}, "description": "Field names, in order. Default: all."},
                "page_size": {"type": "string", "enum": ["letter", "a4", "legal"], "default": "letter"},
                "orientation": {"type": "string", "enum": ["portrait", "landscape"], "default": "portrait"},
                "margins_mm": {"type": "number", "default": 15},
                "fit_to_width": {"type": "boolean", "default": True, "description": "Shrink and wrap columns so the table fits the page width."},
                "font_pt": {"type": "number", "default": 10},
                "show_row_numbers": {"type": "boolean", "default": False},
                "filter": _FILTER_SCHEMA,
                **_REPORT_ROW_PROPERTIES,
            },
            "required": ["table"],
            "additionalProperties": False,
        },
        "handler": tool_create_report,
    },
    {
        "name": "list_reports",
        "description": "The reports kept in a database.",
        "inputSchema": {
            "type": "object",
            "properties": {**_TARGET_PROPERTIES},
            "additionalProperties": False,
        },
        "handler": tool_list_reports,
    },
    {
        "name": "delete_report",
        "description": "Forget a kept report. The table and its rows are untouched.",
        "inputSchema": {
            "type": "object",
            "properties": {**_TARGET_PROPERTIES, "name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
        "handler": tool_delete_report,
    },
    {
        "name": "export_report",
        "description": (
            "Write a report as a PDF. Give a kept report's name, or a table plus any of the "
            "report settings right here. Says in its result whether a file was replaced."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_TARGET_PROPERTIES,
                "file": {"type": "string", "description": "Where to write the PDF."},
                "name": {"type": "string", "description": "A kept report to use."},
                "table": {"type": "string", "description": "Or: the table to report on."},
                "title": {"type": "string", "description": "Printed at the top of page one."},
                "columns": {"type": "array", "items": {"type": "string"}, "description": "Field names, in order. Default: all."},
                "page_size": {"type": "string", "enum": ["letter", "a4", "legal"], "default": "letter"},
                "orientation": {"type": "string", "enum": ["portrait", "landscape"], "default": "portrait"},
                "margins_mm": {"type": "number", "default": 15},
                "fit_to_width": {"type": "boolean", "default": True, "description": "Shrink and wrap columns so the table fits the page width."},
                "font_pt": {"type": "number", "default": 10},
                "show_row_numbers": {"type": "boolean", "default": False},
                "filter": _FILTER_SCHEMA,
                **_REPORT_ROW_PROPERTIES,
                "overwrite": {"type": "boolean", "default": False},
            },
            "required": ["file"],
            "additionalProperties": False,
        },
        "handler": tool_export_report,
    },
    {
        "name": "list_views",
        "description": "Saved views: named filters and sorts kept in the database, per table. Apply one with list_rows and its filter and sort.",
        "inputSchema": {
            "type": "object",
            "properties": {**_TARGET_PROPERTIES, "table": {"type": "string", "description": "Only this table's views."}},
            "additionalProperties": False,
        },
        "handler": tool_list_views,
    },
    {
        "name": "get_view",
        "description": "One saved view: its filter, its sort and whether it is the table's default.",
        "inputSchema": {
            "type": "object",
            "properties": {**_TARGET_PROPERTIES, "table": {"type": "string"}, "name": {"type": "string"}},
            "required": ["table", "name"],
            "additionalProperties": False,
        },
        "handler": tool_get_view,
    },
    {
        "name": "save_view",
        "description": (
            "Keep a filter and/or a sort under a name, like 'Still here' = Moved is not Yes. Refuses a "
            "taken name unless replace is true. default: true makes it the view the table opens with."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_TARGET_PROPERTIES,
                "table": {"type": "string"},
                "name": {"type": "string"},
                "filter": _FILTER_SCHEMA,
                "sort": _SORT_SCHEMA,
                "replace": {"type": "boolean", "default": False},
                "default": {"type": "boolean"},
            },
            "required": ["table", "name"],
            "additionalProperties": False,
        },
        "handler": tool_save_view,
    },
    {
        "name": "delete_view",
        "description": "Forget a saved view. The rows stay; only the saved filter goes.",
        "inputSchema": {
            "type": "object",
            "properties": {**_TARGET_PROPERTIES, "table": {"type": "string"}, "name": {"type": "string"}},
            "required": ["table", "name"],
            "additionalProperties": False,
        },
        "handler": tool_delete_view,
    },
    {
        "name": "add_field",
        "description": "Add a field (column) to a table. Rows already there get nothing in it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_TARGET_PROPERTIES,
                "table": {"type": "string"},
                "label": {"type": "string", "description": "What people see, like 'Moved'."},
                "name": {"type": "string", "description": "Name inside: letters, numbers, underscores. Made from the label if left out."},
                "type": {"type": "string", "enum": list(ALL_FIELD_TYPES), "default": "text",
                         "description": "lookup: points at a row of another table; give target and show."},
                "unique": {"type": "boolean", "default": False, "description": "No two rows may have the same value (blanks may)."},
                "target": {"type": "string", "description": "For a lookup: the table it points at."},
                "show": {"type": "string", "description": "For a lookup: the words field of target it shows, like 'name'."},
            },
            "required": ["table", "label"],
            "additionalProperties": False,
        },
        "handler": tool_add_field,
    },
    {
        "name": "make_lookup",
        "description": (
            "Turn a words field into a lookup: each value becomes the row of `target` whose `show` field has the "
            "same words (case does not matter), like orders.customer names -> rows of customers. Refused, naming "
            "them, when values match no row (add_missing: true adds them to target) or match two rows. Afterwards "
            "list_rows shows the words and gives the row numbers in `ids`; writes may give either."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_TARGET_PROPERTIES,
                "table": {"type": "string"},
                "field": {"type": "string"},
                "target": {"type": "string"},
                "show": {"type": "string"},
                "add_missing": {"type": "boolean", "default": False},
            },
            "required": ["table", "field", "target", "show"],
            "additionalProperties": False,
        },
        "handler": tool_make_lookup,
    },
    {
        "name": "set_unique",
        "description": (
            "Make a field no-repeats (unique: true), like an email or a product code, or let it repeat again. "
            "Refused, with the repeating values, while some already repeat. Not for yes/no fields."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_TARGET_PROPERTIES,
                "table": {"type": "string"},
                "field": {"type": "string"},
                "unique": {"type": "boolean", "default": True},
            },
            "required": ["table", "field"],
            "additionalProperties": False,
        },
        "handler": tool_set_unique,
    },
    {
        "name": "update_rows",
        "description": (
            "Set fields in every row a filter finds, like 'set Moved to Yes where Town is Bend'. "
            "Without a filter it is refused unless every_row is true. Returns how many rows changed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_TARGET_PROPERTIES,
                "table": {"type": "string"},
                "filter": _FILTER_SCHEMA,
                "values": {"type": "object", "description": "Field name to its new value (null for blank)."},
                "every_row": {"type": "boolean", "default": False, "description": "Needed to change every row (no filter)."},
            },
            "required": ["table", "values"],
            "additionalProperties": False,
        },
        "handler": tool_update_rows,
    },
    {
        "name": "delete_rows",
        "description": (
            "Delete every row a filter finds. Cannot be undone. Without a filter it is refused unless "
            "every_row is true. Count first with summarize_rows if unsure."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_TARGET_PROPERTIES,
                "table": {"type": "string"},
                "filter": _FILTER_SCHEMA,
                "every_row": {"type": "boolean", "default": False, "description": "Needed to delete every row (no filter)."},
            },
            "required": ["table"],
            "additionalProperties": False,
        },
        "handler": tool_delete_rows,
    },
    {
        "name": "summarize_rows",
        "description": (
            "How many rows a filter finds (or the whole table), and per field how many are filled in; "
            "numbers get total, average, lowest, highest; dates earliest and latest; yes/no how many Yes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {**_TARGET_PROPERTIES, "table": {"type": "string"}, "filter": _FILTER_SCHEMA},
            "required": ["table"],
            "additionalProperties": False,
        },
        "handler": tool_summarize_rows,
    },
    {
        "name": "add_row_number",
        "description": "Give a table made outside Jubako (no `id`) an automatic row number, so rows can be updated and deleted.",
        "inputSchema": {
            "type": "object",
            "properties": {**_TARGET_PROPERTIES, "table": {"type": "string"}},
            "required": ["table"],
            "additionalProperties": False,
        },
        "handler": tool_add_row_number,
    },
    {
        "name": "rename_field",
        "description": (
            "Rename a field (column) and/or change the label people see. Rows are untouched; "
            "kept forms and reports follow the new name."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_TARGET_PROPERTIES,
                "table": {"type": "string"},
                "field": {"type": "string", "description": "The field's current name."},
                "new_name": {"type": "string", "description": "The new name: letters, numbers, underscores. Leave out to change only the label."},
                "label": {"type": "string", "description": "The words people see for it."},
            },
            "required": ["table", "field"],
            "additionalProperties": False,
        },
        "handler": tool_rename_field,
    },
    {
        "name": "delete_field",
        "description": "Delete a field (column) and everything in it. Cannot be undone. A table keeps at least one field.",
        "inputSchema": {
            "type": "object",
            "properties": {**_TARGET_PROPERTIES, "table": {"type": "string"}, "field": {"type": "string"}},
            "required": ["table", "field"],
            "additionalProperties": False,
        },
        "handler": tool_delete_field,
    },
    {
        "name": "delete_table",
        "description": "Delete a table, all its rows, its form and its reports. Cannot be undone.",
        "inputSchema": {
            "type": "object",
            "properties": {**_TARGET_PROPERTIES, "table": {"type": "string"}},
            "required": ["table"],
            "additionalProperties": False,
        },
        "handler": tool_delete_table,
    },
    {
        "name": "delete_database",
        "description": (
            "Delete a database FILE on this computer (sqlite only) and forget it. Cannot be undone; "
            "needs confirm: true. Server databases are never dropped by Jubako."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "backend": {"type": "string", "enum": ["sqlite"], "default": "sqlite"},
                "path": {"type": "string", "description": "The .jubadb file."},
                "confirm": {"type": "boolean", "default": False},
            },
            "required": ["path", "confirm"],
            "additionalProperties": False,
        },
        "handler": tool_delete_database,
    },
]

HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    tool["name"]: tool["handler"] for tool in TOOLS
}

TOOL_SCHEMAS = [
    {k: v for k, v in tool.items() if k != "handler"} for tool in TOOLS
]


# --------------------------------------------------------------------------
# JSON-RPC plumbing
# --------------------------------------------------------------------------

def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run one tool and wrap it the way MCP wants. Errors come back as text."""
    handler = HANDLERS.get(name)
    if handler is None:
        return _content({"error": f"There is no tool called {name!r}."}, is_error=True)
    try:
        result = handler(arguments or {})
    except JubakoError as error:
        return _content({"error": str(error)}, is_error=True)
    except KeyError as error:
        return _content({"error": f"Missing argument: {error.args[0]!r}"}, is_error=True)
    except Exception as error:  # noqa: BLE001 - never kill the server on one bad call
        return _content({"error": f"{type(error).__name__}: {error}"}, is_error=True)
    return _content(result)


def _content(payload: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    text = json.dumps(payload, indent=2, default=str)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    """Turn one JSON-RPC request into its response (or None for a notice)."""
    method = message.get("method")
    message_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        result: dict[str, Any] = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            "instructions": (
                "Jubako makes simple desktop databases. Start with create_database "
                "(backend 'sqlite' is one file and needs nothing installed), then "
                "import_spreadsheet, then list_tables and list_rows. File paths must be "
                "inside the user's approved folders."
            ),
        }
        return _ok(message_id, result)

    if method in ("notifications/initialized", "initialized"):
        return None

    if method == "ping":
        return _ok(message_id, {})

    if method == "tools/list":
        return _ok(message_id, {"tools": TOOL_SCHEMAS})

    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        return _ok(message_id, call_tool(name, arguments))

    if method == "resources/list":
        return _ok(message_id, {"resources": []})

    if method == "prompts/list":
        return _ok(message_id, {"prompts": []})

    if message_id is None:
        return None
    return _error(message_id, -32601, f"Unknown method: {method}")


def _ok(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id: Any, code: int, text: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": text}}


def serve(stdin=None, stdout=None) -> int:
    """Read newline-delimited JSON-RPC from stdin until it closes."""
    source = stdin or sys.stdin
    sink = stdout or sys.stdout
    for line in source:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            _write(sink, _error(None, -32700, "That was not JSON."))
            continue
        if isinstance(message, list):
            for item in message:
                response = handle(item)
                if response is not None:
                    _write(sink, response)
            continue
        response = handle(message)
        if response is not None:
            _write(sink, response)
    return 0


def _write(sink, payload: dict[str, Any]) -> None:
    sink.write(json.dumps(payload) + "\n")
    sink.flush()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("--tools", "-t"):
        print(json.dumps(TOOL_SCHEMAS, indent=2))
        return 0
    if argv and argv[0] in ("--version", "-V"):
        print(f"{SERVER_NAME} {__version__}")
        return 0
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
