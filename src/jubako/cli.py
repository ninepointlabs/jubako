"""`jubako` on the command line — the same jobs the app does.

    jubako new "My Pets" ~/Documents/pets.jubadb
    jubako import ~/Documents/pets.jubadb data/examples/pets.csv
    jubako tables ~/Documents/pets.jubadb
    jubako rows ~/Documents/pets.jubadb pets
    jubako export ~/Documents/pets.jubadb pets ~/Documents/pets-out.csv
    jubako backends
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import catalog
from .errors import JubakoError
from .exporter import export_table
from .importer import import_spreadsheet, import_workbook, plan_import
from .reports import export_report
from . import schema
from . import templates as _templates
from . import views as _views
from .storage import BACKENDS, create_database, open_database


def _remember(storage: Any) -> None:
    info = storage.describe()
    catalog.remember(
        title=info.title,
        backend=info.backend,
        path=info.location if info.backend == "sqlite" else "",
        where="" if info.backend == "sqlite" else info.location,
    )


def cmd_backends(args: argparse.Namespace) -> int:
    for choice in BACKENDS:
        ready = "ready" if choice.driver_installed() else f"needs {choice.driver_package}"
        print(f"{choice.key:9} {choice.title}  [{ready}]")
        print(f"          {choice.blurb}")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    if args.template:
        _templates.load_template(args.template)  # an unknown key stops here, before a file is made
    with create_database(
        title=args.title, backend="sqlite", path=args.path, overwrite=args.overwrite
    ) as storage:
        if args.template:
            made = _templates.apply_template(storage, args.template, sample_rows=not args.empty)
        _remember(storage)
        print(f"Made the database {storage.title!r} at {storage.location()}")
        if args.template:
            print(f"From the {made['title']} template: tables {', '.join(made['tables'])}; "
                  f"{made['rows_added']} example rows; views {', '.join(made['views'])}; "
                  f"reports {', '.join(made['reports'])}.")
    return 0


def cmd_unique(args: argparse.Namespace) -> int:
    with open_database(backend="sqlite", path=args.path) as storage:
        schema.set_unique(storage, args.table, args.field, not args.off)
    print(f"{args.field} may repeat again." if args.off else f"{args.field} can no longer repeat.")
    return 0


def cmd_add_row_number(args: argparse.Namespace) -> int:
    with open_database(backend="sqlite", path=args.path) as storage:
        result = schema.add_row_number(storage, args.table)
    print(f"{args.table} has a row number now ({result['rows']} rows), so its rows can be changed.")
    return 0


def cmd_templates(args: argparse.Namespace) -> int:
    for item in _templates.list_templates():
        print(f"{item['key']:18} {item['title']}  —  {item['blurb']}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    if args.all_sheets:
        with open_database(backend="sqlite", path=args.path) as storage:
            result = import_workbook(
                storage, args.file, if_exists="replace" if args.replace else "error"
            )
            _remember(storage)
        for item in result["tables"]:
            print(f"Added {item['rows_added']} rows to the table {item['table']!r} ({item['fields']} fields) from sheet {item['sheet']!r}.")
        for item in result["errors"]:
            print(f"Skipped sheet {item['sheet']!r}: {item['error']}")
        return 0 if result["tables"] or not result["errors"] else 2
    with open_database(backend="sqlite", path=args.path) as storage:
        result = import_spreadsheet(
            storage,
            args.file,
            table=args.table,
            if_exists="replace" if args.replace else "error",
            sheet=args.sheet,
        )
        _remember(storage)
    print(f"Added {result['rows_added']} rows to the table {result['table']!r}.")
    for field in result["created_fields"]:
        print(f"  {field['label']}  ->  {field['name']} ({field['type']})")
    if result["note_count"]:
        print(f"{result['note_count']} cells did not match their column's type:")
        for note in result["notes"]:
            print(f"  {note}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    print(json.dumps(plan_import(args.file, sheet=args.sheet), indent=2))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    with open_database(backend="sqlite", path=args.path) as storage:
        result = export_report(
            storage,
            {
                "table": args.table,
                "title": args.title,
                "columns": args.columns.split(",") if args.columns else None,
                "page_size": args.page,
                "orientation": "landscape" if args.landscape else "portrait",
                "fit_to_width": not args.no_fit,
                "filter": _filter_from_args(args),
                "sort": _sort_from_args(args),
                "group_by": args.group_by,
                "totals": dict(item.partition(":")[::2] for item in args.total or []) or None,
                "show_count": True if args.count else None,
                "header_text": args.header,
                "footer_text": args.footer,
                "view": args.view,
            },
            args.out,
            overwrite=args.overwrite,
        )
    print(f"Wrote {result['rows_written']} rows on {result['pages']} page(s) to {result['file']}")
    return 0


def cmd_tables(args: argparse.Namespace) -> int:
    with open_database(backend="sqlite", path=args.path) as storage:
        names = storage.list_tables()
        if not names:
            print("This database has no tables yet. Import a spreadsheet to make one.")
        for name in names:
            info = storage.describe_table(name)
            print(f"{name}  ({len(info.fields)} fields, {info.row_count} rows)")
    return 0


def _filter_from_args(args: argparse.Namespace) -> dict | None:
    """--filter FIELD OP [VALUE], given once or more; --any matches any rule instead of all."""
    rules = []
    for item in args.filter or []:
        if len(item) < 2:
            raise JubakoError("A --filter needs a field and a match, like: --filter age more_than 3")
        rules.append({"field": item[0], "op": item[1], "value": " ".join(item[2:]) if len(item) > 2 else None})
    if not rules:
        return None
    return {"match": "any" if getattr(args, "any", False) else "all", "rules": rules}


def _sort_from_args(args: argparse.Namespace) -> list | None:
    """--sort FIELD or --sort FIELD:desc, given once or more."""
    out = []
    for item in args.sort or []:
        name, _, direction = item.partition(":")
        out.append({"field": name, "descending": direction.lower() in ("desc", "down", "descending")})
    return out or None


def cmd_rows(args: argparse.Namespace) -> int:
    where = _filter_from_args(args)
    with open_database(backend="sqlite", path=args.path) as storage:
        page = storage.list_rows(args.table, limit=args.limit, offset=args.offset, where=where,
                                 sort=_sort_from_args(args))
    if args.json:
        print(json.dumps(page, indent=2, default=str))
        return 0
    print(" | ".join(page["columns"]))
    for row in page["rows"]:
        print(" | ".join("" if value is None else str(value) for value in row))
    print(f"-- {len(page['rows'])} of {page['total']} rows")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    with open_database(backend="sqlite", path=args.path) as storage:
        result = export_table(
            storage, args.table, args.out, file_format=args.format, overwrite=args.overwrite
        )
    print(f"Wrote {result['rows_written']} rows to {result['file']}")
    return 0


def cmd_views(args: argparse.Namespace) -> int:
    with open_database(backend="sqlite", path=args.path) as storage:
        found = _views.list_views(storage, args.table)
    if not found:
        print("No saved views yet. Apply a filter with `rows --filter`, then `save-view`.")
    for view in found:
        star = " (default)" if view.get("default") else ""
        print(f"{view['table']}: {view['name']}{star}  —  {view.get('words', '')}")
    return 0


def cmd_save_view(args: argparse.Namespace) -> int:
    with open_database(backend="sqlite", path=args.path) as storage:
        view = _views.save_view(storage, args.table, args.name, _filter_from_args(args), replace=args.replace,
                                default=True if args.default else None, sort=_sort_from_args(args))
    print(f"Saved the view {view['name']!r} for {args.table}: {view['words']}")
    return 0


def cmd_delete_view(args: argparse.Namespace) -> int:
    with open_database(backend="sqlite", path=args.path) as storage:
        gone = _views.delete_view(storage, args.table, args.name)
    print("Deleted." if gone else "No view has that name.")
    return 0 if gone else 2


def cmd_recent(args: argparse.Namespace) -> int:
    entries = catalog.recent()
    if not entries:
        print("No databases yet.")
    for entry in entries:
        where = entry.get("path") or entry.get("where")
        print(f"{entry.get('title', '?'):24} {entry.get('backend', '?'):9} {where}")
    return 0


def _filter_arguments(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--filter", nargs="+", action="append", metavar="X",
        help="FIELD OP [VALUE], once per rule. OP: is, is_not, empty, not_empty, contains, "
             "starts_with, more_than, less_than, at_least, at_most (or after / before for dates)",
    )
    sub.add_argument("--any", action="store_true", help="Match any --filter rule, not all of them")
    sub.add_argument("--sort", action="append", metavar="FIELD[:desc]", help="Sort by a field, once per field")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jubako", description="A simple desktop database.")
    subs = parser.add_subparsers(dest="command", required=True)

    sub = subs.add_parser("backends", help="Show the kinds of database you can make")
    sub.set_defaults(func=cmd_backends)

    sub = subs.add_parser("new", help="Make a new database file")
    sub.add_argument("title")
    sub.add_argument("path")
    sub.add_argument("--overwrite", action="store_true")
    sub.add_argument("--template", metavar="KEY", help="Start from a template (see `jubako templates`)")
    sub.add_argument("--empty", action="store_true", help="With --template: no example rows")
    sub.set_defaults(func=cmd_new)

    sub = subs.add_parser("templates", help="The ready-made databases you can start from")
    sub.set_defaults(func=cmd_templates)

    sub = subs.add_parser("unique", help="Make a field no-repeats (like an email or a code)")
    sub.add_argument("path")
    sub.add_argument("table")
    sub.add_argument("field")
    sub.add_argument("--off", action="store_true", help="Let it repeat again")
    sub.set_defaults(func=cmd_unique)

    sub = subs.add_parser("add-row-number", help="Give a table made elsewhere a row number, so it can be edited")
    sub.add_argument("path")
    sub.add_argument("table")
    sub.set_defaults(func=cmd_add_row_number)

    sub = subs.add_parser("import", help="Put a spreadsheet into a database")
    sub.add_argument("path")
    sub.add_argument("file")
    sub.add_argument("--table")
    sub.add_argument("--sheet", help="Excel only: which sheet (default: the first)")
    sub.add_argument("--all-sheets", action="store_true", help="Excel only: every sheet becomes its own table")
    sub.add_argument("--replace", action="store_true", help="Replace a table of the same name")
    sub.set_defaults(func=cmd_import)

    sub = subs.add_parser("plan", help="Show what a spreadsheet would become")
    sub.add_argument("file")
    sub.add_argument("--sheet")
    sub.set_defaults(func=cmd_plan)

    sub = subs.add_parser("report", help="Print a table to a tidy, fitted PDF")
    sub.add_argument("path")
    sub.add_argument("table")
    sub.add_argument("out")
    sub.add_argument("--title")
    sub.add_argument("--columns", help="Comma-separated field names, in order")
    sub.add_argument("--page", default="letter", choices=["letter", "a4", "legal"])
    sub.add_argument("--landscape", action="store_true")
    sub.add_argument("--no-fit", action="store_true", help="Keep natural column widths")
    _filter_arguments(sub)
    sub.add_argument("--view", help="Use a saved view's filter and sort")
    sub.add_argument("--group-by", metavar="FIELD", help="A heading per value of this field")
    sub.add_argument("--total", action="append", metavar="FIELD:sum|average", help="Total a number column")
    sub.add_argument("--count", action="store_true", help="Say how many rows (on by default when grouping)")
    sub.add_argument("--header", help="A small line at the top of every page")
    sub.add_argument("--footer", help="Replaces the title at the foot of every page")
    sub.add_argument("--overwrite", action="store_true")
    sub.set_defaults(func=cmd_report)

    sub = subs.add_parser("tables", help="List the tables in a database")
    sub.add_argument("path")
    sub.set_defaults(func=cmd_tables)

    sub = subs.add_parser("rows", help="Show rows from a table")
    sub.add_argument("path")
    sub.add_argument("table")
    sub.add_argument("--limit", type=int, default=20)
    sub.add_argument("--offset", type=int, default=0)
    sub.add_argument("--json", action="store_true")
    _filter_arguments(sub)
    sub.set_defaults(func=cmd_rows)

    sub = subs.add_parser("export", help="Write a table out as CSV, Excel or PDF")
    sub.add_argument("path")
    sub.add_argument("table")
    sub.add_argument("out")
    sub.add_argument("--format", default="csv", choices=["csv", "xlsx", "pdf"])
    sub.add_argument("--overwrite", action="store_true")
    sub.set_defaults(func=cmd_export)

    sub = subs.add_parser("views", help="Saved views (named filters and sorts) in a database")
    sub.add_argument("path")
    sub.add_argument("table", nargs="?")
    sub.set_defaults(func=cmd_views)

    sub = subs.add_parser("save-view", help="Keep a filter and/or a sort under a name")
    sub.add_argument("path")
    sub.add_argument("table")
    sub.add_argument("name")
    _filter_arguments(sub)
    sub.add_argument("--replace", action="store_true")
    sub.add_argument("--default", action="store_true", help="Open the table with this view")
    sub.set_defaults(func=cmd_save_view)

    sub = subs.add_parser("delete-view", help="Forget a saved view (the rows stay)")
    sub.add_argument("path")
    sub.add_argument("table")
    sub.add_argument("name")
    sub.set_defaults(func=cmd_delete_view)

    sub = subs.add_parser("recent", help="Databases you opened lately")
    sub.set_defaults(func=cmd_recent)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except JubakoError as error:
        print(f"Sorry — {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
