"""Send a table back out as a file: CSV, Excel (.xlsx), or PDF.

CSV and xlsx are written here. PDF is a printed report, so it goes through
`reports.export_report` with the table's fields and a plain title.
"""

from __future__ import annotations

import csv
import datetime as _dt
from pathlib import Path
from typing import Any

from .errors import JubakoError
from .fields import BOOLEAN, DATE
from .importer import xlsx_install_hint
from .paths import resolve_under_roots
from .storage.base import Storage, to_jsonable

CHUNK = 1000
FORMATS = ("csv", "xlsx", "pdf")


def export_table(
    storage: Storage,
    table: str,
    file_path: str,
    *,
    file_format: str = "csv",
    overwrite: bool = False,
    include_id: bool = False,
) -> dict[str, Any]:
    """Write every row of a table to a file the user picked."""
    kind = (file_format or "csv").strip().lower().lstrip(".")
    if kind not in FORMATS:
        raise JubakoError(f"Jubako cannot write {kind!r} files. Use: {', '.join(FORMATS)}.")

    if kind == "pdf":
        from .reports import export_report  # noqa: PLC0415

        return export_report(
            storage, {"table": table, "title": storage.describe_table(table).name}, file_path,
            overwrite=overwrite,
        )

    info = storage.describe_table(table)
    target = resolve_under_roots(file_path)
    if target.suffix.lower() != f".{kind}":
        target = target.with_name(target.name + f".{kind}")

    existed = target.exists()
    if existed and not overwrite:
        raise JubakoError(
            f"There is already a file at {target}. Pass overwrite to replace it."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    kinds = ([None] if include_id else []) + [f.type for f in info.fields]
    heading = (["id"] if include_id else []) + [f.title for f in info.fields]

    if kind == "xlsx":
        written = _write_xlsx(storage, table, target, heading, kinds, include_id)
        return {
            "table": table,
            "file": str(target),
            "format": "xlsx",
            "rows_written": written,
            "replaced_existing_file": existed,
        }

    written = 0
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(heading)
        offset = 0
        while True:
            page = storage.list_rows(table, limit=CHUNK, offset=offset)
            if not page["rows"]:
                break
            for row in page["rows"]:
                values = row if include_id else row[1:]
                writer.writerow([_cell(value, kind) for value, kind in zip(values, kinds)])
                written += 1
            offset += CHUNK

    return {
        "table": table,
        "file": str(target),
        "format": "csv",
        "rows_written": written,
        "replaced_existing_file": existed,
    }


def _write_xlsx(
    storage: Storage, table: str, target: Path, heading: list[str], kinds: list, include_id: bool
) -> int:
    """One sheet, bold headings, real Excel types for numbers, dates and yes/no."""
    try:
        from openpyxl import Workbook  # noqa: PLC0415
        from openpyxl.styles import Font  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise JubakoError(
            "Writing Excel files needs the 'openpyxl' package. " + xlsx_install_hint()
        ) from exc

    book = Workbook()
    sheet = book.active
    sheet.title = table[:31] or "Sheet1"
    sheet.append(heading)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    written = 0
    offset = 0
    while True:
        page = storage.list_rows(table, limit=CHUNK, offset=offset)
        if not page["rows"]:
            break
        for row in page["rows"]:
            values = row if include_id else row[1:]
            sheet.append([_excel_cell(value, kind) for value, kind in zip(values, kinds)])
            written += 1
        offset += CHUNK
    for column in sheet.columns:
        longest = max((len(str(c.value)) for c in column if c.value is not None), default=8)
        sheet.column_dimensions[column[0].column_letter].width = min(max(10, longest + 2), 60)
    sheet.freeze_panes = "A2"
    book.save(target)
    return written


def _excel_cell(value: Any, kind: str | None) -> Any:
    if value is None:
        return None
    if kind == BOOLEAN:
        return bool(value)
    if kind == DATE:
        if isinstance(value, _dt.date):
            return value
        try:
            return _dt.date.fromisoformat(str(value)[:10])
        except ValueError:
            return str(value)
    return value


def _cell(value: Any, kind: str | None) -> str:
    """One cell of CSV. Yes/no fields are written as words, not 1 and 0."""
    if value is None:
        return ""
    if kind == BOOLEAN:
        return "yes" if value else "no"
    return str(to_jsonable(value))
