"""The bridge: the only way the QML window talks to the Jubako library.

Every slot returns a plain dict the QML can read (`ok`, `error`, and whatever
the call produced). Nothing here knows SQL; it calls the same functions the
command line and the MCP server use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    Property,
    QAbstractTableModel,
    QModelIndex,
    QObject,
    Qt,
    QThread,
    QUrl,
    Signal,
    Slot,
)

from jubako import catalog, schema, templates, views
from jubako.errors import JubakoError, LookupMissing
from jubako.exporter import export_table
from jubako.fields import (
    ALL_FIELD_TYPES,
    FIELD_TYPE_LABELS,
    FIELD_TYPES,
    LOOKUP,
    TEXT,
    Field,
    field_from_dict,
    slugify_name,
)
from jubako.filters import (
    NEEDS_VALUE,
    OPS,
    filter_match,
    filter_rules,
    filter_words,
    normalise_filter,
    normalise_sort,
    op_words,
    ops_for,
    sort_words,
)
from jubako.importer import import_spreadsheet, import_workbook, plan_import, workbook_plan
from jubako.paths import default_documents_dir, home
from jubako.reports import cell_text, form_for, reset_form, save_form
from jubako.storage import BACKENDS, SQLITE, Storage, create_database, open_database

PAGE_SIZE = 500

BACKEND_WORDS = {"sqlite": "File", "postgres": "PostgreSQL", "mysql": "MySQL / MariaDB"}


class RowsModel(QAbstractTableModel):
    """One table's rows, the way `TableView` wants them: a grid of strings."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._headings: list[str] = []
        self._kinds: list[str | None] = []
        self._names: list[str] = []
        self._rows: list[list[str]] = []
        self._raw: list[list[Any]] = []
        #: For each lookup field, the row numbers behind the words shown (see `Storage.list_rows`).
        self._ids: dict[str, list[Any]] = {}
        #: False for a table with no row number: its cells cannot be typed into.
        self.editable = True
        #: Called with (row_id, field_name, new_text) when a cell is edited in the grid.
        self.editor: Any = None

    def load(self, page: dict[str, Any]) -> None:
        self.beginResetModel()
        self._headings = ["#"] + [field["label"] for field in page["fields"]]
        self._kinds = [None] + [field["type"] for field in page["fields"]]
        self._names = ["id"] + [field["name"] for field in page["fields"]]
        self._raw = [list(row) for row in page["rows"]]
        self._ids = {name: list(ids) for name, ids in dict(page.get("ids") or {}).items()}
        self.editable = bool(page.get("editable", True))
        self._rows = [
            [cell_text(value, self._kinds[i] if i < len(self._kinds) else None)
             for i, value in enumerate(row)]
            for row in self._raw
        ]
        self.endResetModel()

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.isValid() and index.column() > 0 and self.editable:
            base |= Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        """An edit made in the grid. The bridge writes it and reloads the table."""
        if not index.isValid() or index.column() == 0 or self.editor is None:
            return False
        if role not in (Qt.ItemDataRole.EditRole, Qt.ItemDataRole.DisplayRole):
            return False
        row = index.row()
        if row >= len(self._raw) or index.column() >= len(self._names):
            return False
        return bool(self.editor(self._raw[row][0], self._names[index.column()], value))

    @Slot(int, result=int)
    def rowId(self, row: int) -> int:  # noqa: N802
        if 0 <= row < len(self._raw) and self._raw[row][0] is not None:
            return int(self._raw[row][0])
        return 0

    @Slot(int, result=int)
    def rowIndexOf(self, row_id: int) -> int:  # noqa: N802
        for index, row in enumerate(self._raw):
            if row[0] is not None and int(row[0]) == int(row_id):
                return index
        return -1

    @Slot(int, result="QVariantMap")
    def record(self, row: int) -> dict[str, Any]:
        """One row for the form: field name -> value (yes/no as true/false, blanks as "")."""
        if not (0 <= row < len(self._raw)):
            return {"id": 0, "values": {}}
        values: dict[str, Any] = {}
        for column, name in enumerate(self._names):
            if column == 0:
                continue
            raw = self._raw[row][column]
            if self._kinds[column] == "boolean":
                values[name] = bool(raw) if raw is not None else False
            elif self._kinds[column] == LOOKUP:
                # The form picks a row from a list, so it wants the row number, not the words.
                row_number = self._ids.get(name, [None] * len(self._raw))[row]
                values[name] = "" if row_number is None else int(row_number)
            else:
                values[name] = "" if raw is None else str(raw)
        return {"id": int(self._raw[row][0] or 0), "values": values}

    def clear(self) -> None:
        self.load({"fields": [], "rows": []})
        self.beginResetModel()
        self._headings = []
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._headings)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        row = self._rows[index.row()]
        column = index.column()
        return row[column] if column < len(row) else ""

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._headings[section] if section < len(self._headings) else ""
        return section + 1

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802
        return {Qt.ItemDataRole.DisplayRole: b"display"}

    @Slot(int, result=int)
    def columnWidth(self, column: int) -> int:  # noqa: N802
        """A width that fits the longest cell in the column, within reason."""
        if column >= len(self._headings):
            return 120
        longest = len(self._headings[column])
        for row in self._rows[:200]:
            if column < len(row):
                longest = max(longest, len(row[column]))
        return int(min(max(60, longest * 9 + 28), 360))

    @Slot(int, result=str)
    def nameAt(self, column: int) -> str:  # noqa: N802
        """The field name behind a column ("id" for the row number)."""
        return self._names[column] if 0 <= column < len(self._names) else ""

    @Slot(int, result=str)
    def kindAt(self, column: int) -> str:  # noqa: N802
        kind = self._kinds[column] if column < len(self._kinds) else None
        return kind or "id"


class Job(QThread):
    """Run one function off the GUI thread and hand its result back as a dict."""

    done = Signal("QVariantMap")

    def __init__(self, work, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._work = work

    def run(self) -> None:
        try:
            result = dict(self._work())
            result.setdefault("ok", True)
        except JubakoError as error:
            result = {"ok": False, "error": str(error)}
        except Exception as error:  # noqa: BLE001 - the window must hear about it, not crash
            result = {"ok": False, "error": f"Something went wrong: {error}"}
        self.done.emit(result)


class Bridge(QObject):
    """Open one database at a time and answer the window's questions about it."""

    databaseChanged = Signal()
    tablesChanged = Signal()
    tableChanged = Signal()
    busyChanged = Signal()
    importFinished = Signal("QVariantMap")
    message = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._storage: Storage | None = None
        self._tables: list[dict[str, Any]] = []
        self._current_table = ""
        self._shown = 0
        self._total = 0
        self._rows = RowsModel(self)
        self._rows.editor = self._edit_cell
        self._fields: list[dict[str, Any]] = []
        self._form_fields: list[dict[str, Any]] = []
        self._form_title = ""
        self._job: Job | None = None
        self._busy_text = ""
        #: The active filter per table, kept for as long as the database is open.
        self._filters: dict[str, dict[str, Any]] = {}
        self._filter: dict[str, Any] | None = None
        #: The active sort per table: [{field, descending}], empty for "as added".
        self._sorts: dict[str, list[dict[str, Any]]] = {}
        self._sort: list[dict[str, Any]] = []
        self._all_rows = 0
        #: The saved view the current filter came from, per table ("" when none / edited away).
        self._view_names: dict[str, str] = {}
        #: Tables whose default view was already offered once this session.
        self._defaulted: set[str] = set()

    def storage(self) -> Storage | None:
        return self._storage

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._job is not None

    @Property(str, notify=busyChanged)
    def busyText(self) -> str:  # noqa: N802
        return self._busy_text

    def _start(self, text: str, work, on_done) -> dict:
        if self._job is not None:
            return {"ok": False, "error": "Still working on the last thing. One moment."}
        self._busy_text = text
        self._job = Job(work, self)

        def finished(result: dict) -> None:
            job = self._job
            self._job = None
            self._busy_text = ""
            self.busyChanged.emit()
            if job is not None:
                job.deleteLater()
            on_done(dict(result))

        self._job.done.connect(finished)
        self._job.start()
        self.busyChanged.emit()
        return {"ok": True, "pending": True}

    # -- what the window can read ---------------------------------------
    @Property(QObject, constant=True)
    def rows(self) -> RowsModel:
        return self._rows

    @Property(bool, notify=databaseChanged)
    def isOpen(self) -> bool:  # noqa: N802
        return self._storage is not None

    @Property(str, notify=databaseChanged)
    def title(self) -> str:
        return self._storage.title if self._storage else ""

    @Property(str, notify=databaseChanged)
    def location(self) -> str:
        return self._storage.location() if self._storage else ""

    @Property(str, notify=databaseChanged)
    def backendWord(self) -> str:  # noqa: N802
        return BACKEND_WORDS.get(self._storage.backend, "") if self._storage else ""

    @Property(bool, notify=databaseChanged)
    def isLocalFile(self) -> bool:  # noqa: N802
        """True for a .jubadb on this computer: the only kind the app will delete."""
        return bool(self._storage) and self._storage.backend == SQLITE

    @Property("QVariantList", notify=tablesChanged)
    def tables(self) -> list[dict[str, Any]]:
        return list(self._tables)

    @Property(str, notify=tableChanged)
    def currentTable(self) -> str:  # noqa: N802
        return self._current_table

    @Property("QVariantList", notify=tableChanged)
    def fields(self) -> list[dict[str, Any]]:
        """The current table's fields: name, label, type. What the form is built from."""
        return list(self._fields)

    @Property("QVariantList", notify=tableChanged)
    def formFields(self) -> list[dict[str, Any]]:  # noqa: N802
        """The fields in the order and with the labels the table's form asks for."""
        return list(self._form_fields)

    @Property(str, notify=tableChanged)
    def formTitle(self) -> str:  # noqa: N802
        """The heading the current table's form shows."""
        return self._form_title

    @Slot(result="QVariantMap")
    def formDesign(self) -> dict[str, Any]:  # noqa: N802
        """The current table's form, for arranging: title, and every field in order with whether it shows."""
        if self._storage is None or not self._current_table:
            return {"title": "", "items": [], "saved": False}
        form = form_for(self._storage, self._current_table)
        info = {f["name"]: f for f in self._fields}
        items = [{"name": name, "label": form["labels"].get(name, name), "defaultLabel": info[name]["label"],
                  "type": info[name]["type"], "shown": name not in form["hidden"]}
                 for name in form["order"] if name in info]
        return {"title": form["title"], "items": items, "saved": form["saved"]}

    @Slot(str, "QVariantList", result="QVariantMap")
    def saveFormDesign(self, title: str, items: list) -> dict:  # noqa: N802
        """Keep the form's order, labels, title and hidden fields. Items are {name, label, shown}."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        items = [dict(item) for item in items]
        try:
            save_form(self._storage, self._current_table, {
                "title": title,
                "fields": [item["name"] for item in items],
                "labels": {item["name"]: str(item.get("label") or "") for item in items},
                "hidden": [item["name"] for item in items if not item.get("shown", True)],
            })
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self.selectTable(self._current_table)
        self.message.emit("Kept the form. Hidden fields keep their values.")
        return {"ok": True}

    @Slot(result="QVariantMap")
    def resetFormDesign(self) -> dict:  # noqa: N802
        """Back to the plain form: every field, in table order, with the field labels."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        reset_form(self._storage, self._current_table)
        self.selectTable(self._current_table)
        return {"ok": True}

    @Slot(result="QVariantList")
    def fieldTypes(self) -> list[dict[str, str]]:  # noqa: N802
        """The kinds a spreadsheet column can be read as (the import preview)."""
        return [{"key": key, "label": FIELD_TYPE_LABELS[key]} for key in FIELD_TYPES]

    @Slot(result="QVariantList")
    def allFieldTypes(self) -> list[dict[str, str]]:  # noqa: N802
        """Every kind of field, a lookup ("A row of another table") too."""
        return [{"key": key, "label": FIELD_TYPE_LABELS[key]} for key in ALL_FIELD_TYPES]

    # -- lookups ------------------------------------------------------------------
    @Slot(str, result="QVariantList")
    def lookupChoices(self, field: str) -> list[dict[str, Any]]:  # noqa: N802
        """The rows a lookup field of the current table can point at: [{id, text}], A to Z."""
        info = next((f for f in self._fields if f["name"] == field and f["type"] == LOOKUP), None)
        if self._storage is None or info is None:
            return []
        try:
            page = self._storage.list_rows(info["target"], limit=5000, sort=[{"field": info["show"]}])
        except JubakoError:
            return []
        position = page["columns"].index(info["show"])
        return [{"id": int(row[0]), "text": "" if row[position] is None else str(row[position]) or f"#{row[0]}"}
                for row in page["rows"]]

    @Slot(result="QVariantList")
    def lookupTargets(self) -> list[dict[str, Any]]:  # noqa: N802
        """Tables a lookup can point at (they have row numbers), each with the words fields it could show."""
        if self._storage is None:
            return []
        out = []
        for table in self._storage.list_tables():
            try:
                info = self._storage.describe_table(table)
            except JubakoError:
                continue
            words = [{"name": f.name, "label": f.title} for f in info.fields if f.type == TEXT]
            if info.has_row_id and words:
                out.append({"name": table, "fields": words})
        return out

    @Slot(str, str, str, str, result="QVariantMap")
    def addLookupField(self, label: str, name: str, target: str, show: str) -> dict:  # noqa: N802
        """Add a field to the current table that points at rows of `target`, showing their `show` field."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        try:
            result = schema.add_field(self._storage, self._current_table, label=label, name=name,
                                      field_type=LOOKUP, target=target, show=show)
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._refresh_tables(select=self._current_table)
        added = result["fields"][-1]
        self.message.emit(f"Added {added['label']}: it points at rows of {target}.")
        return {"ok": True, "name": added["name"]}

    @Slot(str, str, str, bool, result="QVariantMap")
    def makeLookup(self, field: str, target: str, show: str, add_missing: bool) -> dict:  # noqa: N802
        """Turn a words field of the current table into a lookup. Values that match no row come back as
        `missing` (and nothing changes) unless `add_missing`."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        try:
            result = schema.make_lookup(self._storage, self._current_table, field, target, show, add_missing=add_missing)
        except LookupMissing as error:
            return {"ok": False, "error": str(error), "missing": error.missing}
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._refresh_tables(select=self._current_table)
        label = next((f["label"] for f in self._fields if f["name"] == field), field)
        added = f" Added {len(result['added'])} to {target}." if result["added"] else ""
        self.message.emit(f"{label} now points at rows of {target}.{added}")
        return {"ok": True, "added": result["added"]}

    @Property("QVariantMap", notify=tableChanged)
    def filter(self) -> dict[str, Any]:
        """The current table's first rule: {field, op, value}, or {} for all rows."""
        rules = self.filterRules
        return rules[0] if rules else {}

    @Property("QVariantList", notify=tableChanged)
    def filterRules(self) -> list[dict[str, Any]]:  # noqa: N802
        """Every rule of the current filter, values as text the way the bar shows them."""
        out = []
        for rule in filter_rules(self._filter):
            rule = dict(rule)
            if isinstance(rule.get("value"), bool):
                rule["value"] = "yes" if rule["value"] else "no"
            elif rule.get("value") is not None:
                rule["value"] = cell_text(rule["value"], None)  # 3000, not 3000.0
            out.append(rule)
        return out

    @Property(str, notify=tableChanged)
    def filterMatch(self) -> str:  # noqa: N802
        """"all" or "any": how the current rules combine."""
        return filter_match(self._filter)

    @Property(str, notify=tableChanged)
    def filterWords(self) -> str:  # noqa: N802
        """The rule in plain words, like "Moved is not Yes"; blank when showing all rows."""
        if not self._filter:
            return ""
        return filter_words(self._field_objects(), self._filter)

    @Property("QVariantList", notify=tableChanged)
    def sort(self) -> list[dict[str, Any]]:
        """The current table's sort: [{field, descending}], empty for the order rows were added."""
        return [dict(item) for item in self._sort]

    @Property(str, notify=tableChanged)
    def sortWords(self) -> str:  # noqa: N802
        """The sort in plain words, like "Age, highest first"; blank when unsorted."""
        return sort_words(self._field_objects(), self._sort)

    def _field_objects(self) -> list[Field]:
        return [field_from_dict(f) for f in self._fields]

    @Property(bool, notify=tableChanged)
    def canEdit(self) -> bool:  # noqa: N802
        """False for a table made outside Jubako with no row number: it can be read, not edited."""
        return self._rows.editable

    @Slot(result="QVariantMap")
    def addRowNumber(self) -> dict:  # noqa: N802
        """Give the current table (made outside Jubako) a row number, so it can be edited."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        try:
            schema.add_row_number(self._storage, self._current_table)
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._refresh_tables(select=self._current_table)
        self.message.emit(f"{self._current_table} has a row number now, so its rows can be changed.")
        return {"ok": True}

    @Slot(str, bool, result="QVariantMap")
    def setUnique(self, name: str, unique: bool) -> dict:  # noqa: N802
        """Turn "no repeats" on or off for a field of the current table."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        try:
            schema.set_unique(self._storage, self._current_table, name, unique)
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._refresh_tables(select=self._current_table)
        label = next((f["label"] for f in self._fields if f["name"] == name), name)
        self.message.emit(f"{label} can no longer repeat." if unique else f"{label} may repeat again.")
        return {"ok": True}

    @Property(int, notify=tableChanged)
    def allRows(self) -> int:  # noqa: N802
        """How many rows the table has before the filter."""
        return self._all_rows

    # -- saved views ---------------------------------------------------------------
    @Property("QVariantList", notify=tableChanged)
    def views(self) -> list[dict[str, Any]]:
        """The current table's saved views: name, words, default."""
        if self._storage is None or not self._current_table:
            return []
        try:
            return [{"name": v["name"], "words": v.get("words", ""), "default": bool(v.get("default"))}
                    for v in views.list_views(self._storage, self._current_table)]
        except JubakoError:
            return []

    @Property(str, notify=tableChanged)
    def currentView(self) -> str:  # noqa: N802
        """The saved view whose filter is on screen, or blank."""
        return self._view_names.get(self._current_table, "") if (self._filter or self._sort) else ""

    @Slot(str, bool, bool, result="QVariantMap")
    def saveView(self, name: str, replace: bool, default: bool) -> dict:  # noqa: N802
        """Keep the filter on screen under a name. A taken name needs `replace`."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        if not self._filter and not self._sort:
            return {"ok": False, "error": "Apply a filter or a sort first, then save it as a view."}
        existing = views.get_view(self._storage, self._current_table, name)
        if existing and not replace:
            return {"ok": False, "needsConfirm": True, "name": existing["name"]}
        try:
            view = views.save_view(self._storage, self._current_table, name, self._filter,
                                   replace=replace, default=default or None, sort=self._sort)
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._view_names[self._current_table] = view["name"]
        self.tableChanged.emit()
        self.message.emit(f"Saved the view \u201c{view['name']}\u201d.")
        return {"ok": True, "name": view["name"]}

    @Slot(str, result="QVariantMap")
    def applyView(self, name: str) -> dict:  # noqa: N802
        """Show the rows a saved view asks for. A view on a field that is gone is dropped."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        view = views.get_view(self._storage, self._current_table, name)
        if view is None:
            return {"ok": False, "error": f"There is no view called \u201c{name}\u201d."}
        fields = self._field_objects()
        try:
            spec = normalise_filter(fields, view.get("filter"))
            order = normalise_sort(fields, view.get("sort"))
        except JubakoError:
            views.delete_view(self._storage, self._current_table, name)
            self.tableChanged.emit()
            return {"ok": False, "error": f"The view \u201c{name}\u201d used a field that is gone, so it was removed."}
        self._set_filter_state(spec)
        self._sorts[self._current_table] = order
        self._view_names[self._current_table] = view["name"]
        return self.selectTable(self._current_table)

    @Slot(str, result="QVariantMap")
    def deleteView(self, name: str) -> dict:  # noqa: N802
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        gone = views.delete_view(self._storage, self._current_table, name)
        if self._view_names.get(self._current_table) == name:
            self._view_names[self._current_table] = ""
        self.tableChanged.emit()
        if gone:
            self.message.emit(f"Deleted the view \u201c{name}\u201d. The rows are still there.")
        return {"ok": gone, "error": "" if gone else "That view was already gone."}

    @Slot(str, str, result="QVariantMap")
    def renameView(self, old: str, new: str) -> dict:  # noqa: N802
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        try:
            view = views.rename_view(self._storage, self._current_table, old, new)
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        if self._view_names.get(self._current_table) == old:
            self._view_names[self._current_table] = view["name"]
        self.tableChanged.emit()
        return {"ok": True, "name": view["name"]}

    @Slot(str, bool, result="QVariantMap")
    def setDefaultView(self, name: str, default: bool) -> dict:  # noqa: N802
        """Make (or unmake) a view the one this table opens with."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        view = views.get_view(self._storage, self._current_table, name)
        if view is None:
            return {"ok": False, "error": f"There is no view called \u201c{name}\u201d."}
        try:
            views.save_view(self._storage, self._current_table, name, view.get("filter"), replace=True,
                            default=default, sort=view.get("sort"))
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self.tableChanged.emit()
        return {"ok": True}

    @Slot(result="QVariantList")
    def filterOps(self) -> list[dict[str, Any]]:  # noqa: N802
        """Every match there is, in plain words."""
        return [{"key": op, "label": op_words(op), "needsValue": op in NEEDS_VALUE} for op in OPS]

    @Slot(str, result="QVariantList")
    def filterOpsFor(self, field_type: str) -> list[dict[str, Any]]:  # noqa: N802
        """The matches that fit a field of this type: no "contains" on a number, "is after" for a date."""
        return [{"key": op, "label": op_words(op, field_type), "needsValue": op in NEEDS_VALUE}
                for op in ops_for(field_type or "text")]

    @Slot(str, str, str, result="QVariantMap")
    def setFilter(self, field: str, op: str, value: str) -> dict:  # noqa: N802
        """Show only rows where <field> <op> <value>. Remembered per table while the database is open."""
        return self.setFilterRules("all", [{"field": field, "op": op, "value": value}])

    @Slot(str, "QVariantList", result="QVariantMap")
    def setFilterRules(self, match: str, rules: list) -> dict:  # noqa: N802
        """Show only rows that meet all (or any) of these rules. Each rule is {field, op, value}."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        clean = []
        for rule in rules:
            rule = dict(rule)
            if rule.get("op") not in NEEDS_VALUE:
                rule["value"] = None
            clean.append(rule)
        try:
            spec = normalise_filter(self._field_objects(), {"match": match or "all", "rules": clean})
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._set_filter_state(spec)
        return self.selectTable(self._current_table)

    def _set_filter_state(self, spec: dict[str, Any] | None) -> None:
        """Remember a new filter for the current table; a changed rule detaches it from its view."""
        table = self._current_table
        if spec:
            if spec != self._filters.get(table):
                self._view_names[table] = ""
            self._filters[table] = spec
        else:
            if self._filters.pop(table, None) is not None:
                self._view_names[table] = ""

    @Slot(result="QVariantMap")
    def clearFilter(self) -> dict:  # noqa: N802
        if not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        self._filters.pop(self._current_table, None)
        self._view_names[self._current_table] = ""
        return self.selectTable(self._current_table)

    # -- the rows on screen, all at once ---------------------------------------
    @Slot(str, str, bool, result="QVariantMap")
    def changeMatching(self, field: str, value: str, blank: bool) -> dict:  # noqa: N802
        """Set one field in every row the filter shows (every row when no filter is on). The window confirmed."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        new_value = None if blank else _from_qml(value)
        if new_value is None and not blank:
            return {"ok": False, "error": "Type the new value, or tick “Make it blank”."}
        try:
            changed = self._storage.update_matching(self._current_table, self._filter, {field: new_value}, every_row=True)
        except (ValueError, TypeError) as error:
            return {"ok": False, "error": _value_words(error, self._fields, {field: new_value})}
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._refresh_tables(select=self._current_table)
        label = next((f["label"] for f in self._fields if f["name"] == field), field)
        self.message.emit(f"Changed {label} in {changed} row{'s' if changed != 1 else ''}.")
        return {"ok": True, "changed": changed}

    @Slot(result="QVariantMap")
    def deleteMatching(self) -> dict:  # noqa: N802
        """Delete every row the filter shows (every row when no filter is on). The window confirmed."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        try:
            deleted = self._storage.delete_matching(self._current_table, self._filter, every_row=True)
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._refresh_tables(select=self._current_table)
        self.message.emit(f"Deleted {deleted} row{'s' if deleted != 1 else ''}.")
        return {"ok": True, "deleted": deleted}

    @Slot(result="QVariantMap")
    def summary(self) -> dict:
        """Counts and totals for the rows the filter shows: what each field adds up to."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        try:
            result = self._storage.summarize(self._current_table, self._filter)
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        result["ok"] = True
        result.pop("filter", None)
        return result

    @Slot(str, result="QVariantMap")
    def sortBy(self, field: str) -> dict:  # noqa: N802
        """A tap on a column heading: sort by it going up, then down, then back to unsorted."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        current = self._sorts.get(self._current_table) or []
        if current and current[0]["field"] == field and len(current) == 1:
            order = [] if current[0]["descending"] else [{"field": field, "descending": True}]
        else:
            order = [{"field": field, "descending": False}]
        return self.setSort(order)

    @Slot("QVariantList", result="QVariantMap")
    def setSort(self, order: list) -> dict:  # noqa: N802
        """Sort the current table by these fields: [{field, descending}]. Empty for unsorted."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        try:
            spec = normalise_sort(self._field_objects(), [dict(item) for item in order])
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        if spec != (self._sorts.get(self._current_table) or []):
            self._view_names[self._current_table] = ""
        if spec:
            self._sorts[self._current_table] = spec
        else:
            self._sorts.pop(self._current_table, None)
        return self.selectTable(self._current_table)

    @Slot(str, result=str)
    def slugName(self, label: str) -> str:  # noqa: N802
        """"Vet's phone" -> "vet_s_phone": the name inside, made from a label."""
        return slugify_name(label, fallback="field") if (label or "").strip() else ""

    @Property(int, notify=tableChanged)
    def shownRows(self) -> int:  # noqa: N802
        return self._shown

    @Property(int, notify=tableChanged)
    def totalRows(self) -> int:  # noqa: N802
        return self._total

    # -- lists for the home screen and the chooser ------------------------
    @Slot(result="QVariantList")
    def backends(self) -> list[dict[str, Any]]:
        return [
            {
                "key": choice.key,
                "title": choice.title,
                "blurb": choice.blurb,
                "needsServer": choice.needs_server,
                "ready": choice.driver_installed(),
                "driver": choice.driver_package,
            }
            for choice in BACKENDS
        ]

    @Slot(result="QVariantList")
    def recent(self) -> list[dict[str, Any]]:
        out = []
        for entry in catalog.recent():
            backend = entry.get("backend", SQLITE)
            out.append(
                {
                    "title": entry.get("title") or "Database",
                    "backend": backend,
                    "backendWord": BACKEND_WORDS.get(backend, backend),
                    "path": entry.get("path", ""),
                    "where": entry.get("where", ""),
                    "lastOpened": entry.get("last_opened", ""),
                }
            )
        return out

    @Slot(result=str)
    def documentsFolder(self) -> str:  # noqa: N802
        return QUrl.fromLocalFile(str(default_documents_dir())).toString()

    @Slot(result=str)
    def homeFolder(self) -> str:  # noqa: N802
        return QUrl.fromLocalFile(str(home())).toString()

    @Slot(str, result=str)
    def localPath(self, url: str) -> str:  # noqa: N802
        """`file:///home/tim/x.jubadb` -> `/home/tim/x.jubadb`."""
        parsed = QUrl(url)
        return parsed.toLocalFile() if parsed.isLocalFile() else url

    @Slot(str, result=str)
    def suggestedDatabaseName(self, spreadsheet: str) -> str:  # noqa: N802
        stem = Path(self.localPath(spreadsheet)).stem or "my-database"
        return f"{stem}.jubadb"

    # -- making and opening --------------------------------------------------
    @Slot(str, str, str, "QVariantMap", result="QVariantMap")
    def newDatabase(self, backend: str, path: str, title: str, connection: dict) -> dict:  # noqa: N802
        connection = {k: v for k, v in dict(connection).items() if v not in ("", None)}
        try:
            storage = create_database(
                title=title, backend=backend or SQLITE, path=self.localPath(path) or None,
                overwrite=backend in ("", SQLITE), connection=connection,
            )
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._adopt(storage)
        self.message.emit("New database made. Now make a table, or import a spreadsheet.")
        return {"ok": True}

    @Slot(result="QVariantList")
    def templates(self) -> list[dict[str, Any]]:
        """The ready-made databases: key, title, blurb, tables."""
        return templates.list_templates()

    @Slot(str, str, str, "QVariantMap", str, bool, result="QVariantMap")
    def newFromTemplate(self, backend: str, path: str, title: str, connection: dict,  # noqa: N802
                        template: str, sample_rows: bool) -> dict:
        """A new database with a template's tables, views and reports (and, if asked, its example rows)."""
        try:
            chosen = templates.load_template(template)
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        made = self.newDatabase(backend, path, (title or "").strip() or chosen["title"], connection)
        if not made["ok"]:
            return made
        try:
            result = templates.apply_template(self._storage, template, sample_rows=sample_rows)
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._refresh_tables(select=result["opens"])
        rows = f" with {result['rows_added']} example rows" if result["rows_added"] else ""
        self.message.emit(f"Made from the {result['title']} template{rows}. Try Views\u2026 and Print report.")
        return {"ok": True, "tables": result["tables"]}

    @Slot(str, str, "QVariantMap", result="QVariantMap")
    def openDatabase(self, backend: str, path: str, connection: dict) -> dict:  # noqa: N802
        connection = {k: v for k, v in dict(connection).items() if v not in ("", None)}
        try:
            storage = open_database(
                backend=backend or SQLITE, path=self.localPath(path) or None, connection=connection
            )
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._adopt(storage)
        return {"ok": True}

    @Slot(int, result="QVariantMap")
    def openRecent(self, index: int) -> dict:  # noqa: N802
        entries = catalog.recent()
        if index < 0 or index >= len(entries):
            return {"ok": False, "error": "That database is not in the list any more."}
        entry = entries[index]
        backend = entry.get("backend", SQLITE)
        if backend == SQLITE:
            result = self.openDatabase(SQLITE, entry.get("path", ""), {})
            if not result["ok"]:
                catalog.forget(backend=SQLITE, path=entry.get("path", ""))
            return result
        # A server: we remember where it is, never the password, so ask.
        return {
            "ok": False,
            "needsConnection": True,
            "backend": backend,
            "title": entry.get("title", ""),
            "connection": _parse_where(backend, entry.get("where", "")),
        }

    @Slot(int, result="QVariantMap")
    def removeRecent(self, index: int) -> dict:  # noqa: N802
        """Forget a database in the recent list. The database itself is untouched."""
        entries = catalog.recent()
        if index < 0 or index >= len(entries):
            return {"ok": False, "error": "That database is not in the list any more."}
        entry = entries[index]
        catalog.forget(backend=entry.get("backend", SQLITE), path=entry.get("path", ""), where=entry.get("where", ""))
        return {"ok": True}

    @Slot(int, result="QVariantMap")
    def deleteRecentFile(self, index: int) -> dict:  # noqa: N802
        """Delete a database file from the recent list, for good."""
        entries = catalog.recent()
        if index < 0 or index >= len(entries):
            return {"ok": False, "error": "That database is not in the list any more."}
        entry = entries[index]
        if entry.get("backend", SQLITE) != SQLITE or not entry.get("path"):
            return {"ok": False, "error": "Only a database file on this computer can be deleted here."}
        path = entry["path"]
        if self._storage is not None and self._storage.backend == SQLITE and self._storage.location() == path:
            return self.deleteDatabase()
        try:
            schema.delete_database_file(None, path)
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self.message.emit(f"Deleted {Path(path).name}.")
        return {"ok": True}

    @Slot(str, result="QVariantMap")
    def renameDatabase(self, title: str) -> dict:  # noqa: N802
        """Change the open database's title (Home and the top of the window follow)."""
        if self._storage is None:
            return {"ok": False, "error": "No database is open."}
        try:
            result = schema.rename_database(self._storage, title)
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        info = self._storage.describe()
        catalog.remember(
            title=info.title, backend=info.backend,
            path=info.location if info.backend == SQLITE else "",
            where="" if info.backend == SQLITE else info.location,
        )
        self.databaseChanged.emit()
        self.message.emit(f"Renamed the database to \u201c{result['title']}\u201d.")
        return {"ok": True, "title": result["title"]}

    @Slot(str, result="QVariantMap")
    def saveCopy(self, url: str) -> dict:  # noqa: N802
        """Write a copy of the open database file. The save dialog already asked about replacing."""
        if self._storage is None:
            return {"ok": False, "error": "No database is open."}
        try:
            result = schema.save_copy(self._storage, self.localPath(url), overwrite=True)
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self.message.emit(f"Saved a copy as {Path(result['file']).name}. You are still working in this one.")
        return {"ok": True, "file": result["file"]}

    @Slot(result=str)
    def copyName(self) -> str:  # noqa: N802
        """A suggested file for "Save a copy": next to the database, with "copy" and today's date."""
        if self._storage is None or self._storage.backend != SQLITE:
            return ""
        import datetime as _dt  # noqa: PLC0415

        here = Path(self._storage.location())
        return QUrl.fromLocalFile(str(here.with_name(f"{here.stem} copy {_dt.date.today().isoformat()}{here.suffix}"))).toString()

    @Slot(result="QVariantMap")
    def deleteDatabase(self) -> dict:  # noqa: N802
        """Delete the open database file and go back to Home. Server databases are never dropped."""
        if self._storage is None:
            return {"ok": False, "error": "No database is open."}
        if self._storage.backend != SQLITE:
            return {"ok": False, "error": "Only a database file on this computer can be deleted here. "
                    "A server database is left alone."}
        path = self._storage.location()
        storage, self._storage = self._storage, None
        try:
            schema.delete_database_file(storage, path)
        except JubakoError as error:
            self._storage = storage
            return {"ok": False, "error": str(error)}
        self._tables = []
        self._current_table = ""
        self._shown = self._total = 0
        self._rows.clear()
        self.tablesChanged.emit()
        self.tableChanged.emit()
        self.databaseChanged.emit()
        self.message.emit(f"Deleted {Path(path).name}.")
        return {"ok": True, "file": path}

    @Slot(str, str, result="QVariantMap")
    def importIntoNew(self, spreadsheet: str, database_path: str) -> dict:  # noqa: N802
        """The first-run path: a spreadsheet becomes a brand new database."""
        title = Path(self.localPath(spreadsheet)).stem.replace("_", " ").replace("-", " ").title()
        made = self.newDatabase(SQLITE, database_path, title, {})
        if not made["ok"]:
            return made
        return self.importSpreadsheet(spreadsheet, True)

    @Slot(str, str, result="QVariantMap")
    def planImport(self, spreadsheet: str, sheet: str) -> dict:  # noqa: N802
        """What a spreadsheet would become: the wizard shows this and lets people change it."""
        try:
            plan = plan_import(self.localPath(spreadsheet), sheet=sheet or None)
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        plan["ok"] = True
        plan["exists"] = bool(self._storage and self._storage.has_table(plan["table"]))
        return plan

    @Slot(str, str, str, "QVariantList", bool, result="QVariantMap")
    def importPlanned(self, spreadsheet: str, sheet: str, table: str, fields: list, replace: bool) -> dict:  # noqa: N802
        """Import with the wizard's choices: table name and each column's type.

        For a file database the work runs on a worker thread with its own
        connection, so a big spreadsheet does not freeze the window; the result
        arrives through `importFinished`. A server database imports in place.
        """
        if self._storage is None:
            return {"ok": False, "error": "Open a database first."}
        path = self.localPath(spreadsheet)
        try:
            chosen = [Field(name=f["name"], type=f["type"], label=f.get("label") or None) for f in fields] or None
            table = (table or "").strip() or None
            if not replace:
                plan = plan_import(path, sheet=sheet or None)
                if self._storage.has_table(table or plan["table"]):
                    return {"ok": False, "needsConfirm": True, "table": table or plan["table"]}
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except JubakoError as error:
            return {"ok": False, "error": str(error)}

        if_exists = "replace" if replace else "error"

        if self._storage.backend != SQLITE:
            try:
                report = import_spreadsheet(
                    self._storage, path, table=table, fields=chosen, sheet=sheet or None, if_exists=if_exists
                )
            except (ValueError, JubakoError) as error:
                return {"ok": False, "error": str(error)}
            return self._imported(report)

        location = self._storage.location()

        def work() -> dict:
            with open_database(backend=SQLITE, path=location) as own:
                return import_spreadsheet(
                    own, path, table=table, fields=chosen, sheet=sheet or None, if_exists=if_exists
                )

        def done(result: dict) -> None:
            if result.get("ok", True) and "table" in result:
                result = self._imported(result)
            self.importFinished.emit(result)

        return self._start("Importing…", work, done)

    def _imported(self, report: dict) -> dict:
        self._refresh_tables(select=report["table"])
        note = f" {report['note_count']} cells did not fit and were kept as words." if report["note_count"] else ""
        self.message.emit(f"Added {report['rows_added']} rows to {report['table']}.{note}")
        return {"ok": True, "table": report["table"], "rowsAdded": report["rows_added"],
                "noteCount": report["note_count"], "notes": list(report["notes"])}

    @Slot(str, result="QVariantList")
    def workbookPlan(self, spreadsheet: str) -> list:  # noqa: N802
        """Each sheet and the table it would become, and whether that table exists."""
        try:
            plan = workbook_plan(self.localPath(spreadsheet))
        except JubakoError:
            return []
        for item in plan:
            item["exists"] = bool(self._storage and self._storage.has_table(item["table"]))
        return plan

    @Slot(str, bool, result="QVariantMap")
    def importAllSheets(self, spreadsheet: str, replace: bool) -> dict:  # noqa: N802
        """Every sheet becomes its own table, with guessed types. One confirm covers all clashes."""
        if self._storage is None:
            return {"ok": False, "error": "Open a database first."}
        path = self.localPath(spreadsheet)
        if not replace:
            clashes = [item["table"] for item in self.workbookPlan(spreadsheet) if item["exists"]]
            if clashes:
                return {"ok": False, "needsConfirm": True, "tables": clashes, "table": clashes[0]}
        if_exists = "replace" if replace else "error"

        if self._storage.backend != SQLITE:
            try:
                report = import_workbook(self._storage, path, if_exists=if_exists)
            except JubakoError as error:
                return {"ok": False, "error": str(error)}
            return self._imported_all(report)

        location = self._storage.location()

        def work() -> dict:
            with open_database(backend=SQLITE, path=location) as own:
                return import_workbook(own, path, if_exists=if_exists)

        def done(result: dict) -> None:
            if result.get("ok", True) and "tables" in result:
                result = self._imported_all(result)
            self.importFinished.emit(result)

        return self._start("Importing every sheet\u2026", work, done)

    def _imported_all(self, report: dict) -> dict:
        tables = [item["table"] for item in report["tables"]]
        errors = [f"{item['sheet']}: {item['error']}" for item in report["errors"]]
        self._refresh_tables(select=tables[0] if tables else self._current_table)
        if tables:
            word = "table" if len(tables) == 1 else "tables"
            text = f"Made {len(tables)} {word}: {', '.join(tables)}."
            if errors:
                text += f" Skipped {len(errors)} sheet{'s' if len(errors) != 1 else ''}."
            self.message.emit(text)
        return {"ok": bool(tables), "tables": tables, "errors": errors,
                "error": "" if tables else ("Nothing was imported. " + " ".join(errors))}

    # -- fields and tables ------------------------------------------------------
    @Slot(str, "QVariantList", result="QVariantMap")
    def newTable(self, table: str, fields: list) -> dict:  # noqa: N802
        """Make an empty table with these fields ({label, type, unique}) and show it."""
        if self._storage is None:
            return {"ok": False, "error": "Open a database first."}
        try:
            result = schema.create_table(self._storage, table, [dict(f) for f in fields])
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._refresh_tables(select=result["table"])
        count = len(result["fields"])
        self.message.emit(f"Made the table {result['table']} with {count} field{'s' if count != 1 else ''}.")
        return {"ok": True, "table": result["table"], "fields": result["fields"]}

    @Slot(str, result=str)
    def tableName(self, label: str) -> str:  # noqa: N802
        """"Vet visits" -> "vet_visits": a new table's name inside, made from what was typed."""
        return slugify_name(label, fallback="table") if (label or "").strip() else ""

    @Slot(str, str, str, result="QVariantMap")
    @Slot(str, str, str, bool, result="QVariantMap")
    def addField(self, label: str, name: str, field_type: str, unique: bool = False) -> dict:  # noqa: N802
        """Add a field to the current table. Rows already there get nothing in it. `unique`: no repeats."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        try:
            result = schema.add_field(
                self._storage, self._current_table, label=label, name=name, field_type=field_type or "text",
                unique=unique,
            )
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._refresh_tables(select=self._current_table)
        self.message.emit(f"Added the field {result['fields'][-1]['label']}.")
        return {"ok": True, "fields": result["fields"]}

    @Slot(str, str, str, result="QVariantMap")
    def renameField(self, old: str, new: str, label: str) -> dict:  # noqa: N802
        """Change a field's name and/or label. Blank name means keep it."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        new = (new or "").strip() or old
        try:
            result = schema.rename_field(
                self._storage, self._current_table, old, new, label=(label or "").strip() or None
            )
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._refresh_tables(select=self._current_table)
        self.message.emit(f"Renamed {old} to {new}." if new != old else f"Relabelled {new}.")
        return {"ok": True, "fields": result["fields"]}

    @Slot(str, result="QVariantMap")
    def deleteField(self, name: str) -> dict:  # noqa: N802
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        try:
            result = schema.drop_field(self._storage, self._current_table, name)
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._refresh_tables(select=self._current_table)
        self.message.emit(f"Deleted the field {name}.")
        return {"ok": True, "fields": result["fields"]}

    @Slot(str, result="QVariantMap")
    def deleteTable(self, table: str) -> dict:  # noqa: N802
        if self._storage is None:
            return {"ok": False, "error": "Open a database first."}
        try:
            result = schema.drop_table(self._storage, table)
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._refresh_tables()
        self.message.emit(f"Deleted the table {table} and its {result['rows_deleted']} rows.")
        return {"ok": True, "rowsDeleted": result["rows_deleted"]}

    @Slot(str, str, result="QVariantMap")
    def exportTable(self, url: str, file_format: str) -> dict:  # noqa: N802
        """Write the current table out. The save dialog already asked about replacing."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        try:
            result = export_table(
                self._storage, self._current_table, self.localPath(url),
                file_format=file_format, overwrite=True,
            )
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self.message.emit(f"Wrote {result['rows_written']} rows to {Path(result['file']).name}.")
        return {"ok": True, "file": result["file"], "rows": result["rows_written"]}

    @Slot(str, bool, result="QVariantMap")
    def importSpreadsheet(self, spreadsheet: str, replace: bool) -> dict:  # noqa: N802
        if self._storage is None:
            return {"ok": False, "error": "Open a database first."}
        path = self.localPath(spreadsheet)
        try:
            plan = plan_import(path)
            if not replace and self._storage.has_table(plan["table"]):
                return {"ok": False, "needsConfirm": True, "table": plan["table"]}
            report = import_spreadsheet(
                self._storage, path, if_exists="replace" if replace else "error"
            )
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._refresh_tables(select=report["table"])
        self.message.emit(f"Added {report['rows_added']} rows to {report['table']}.")
        return {"ok": True, "table": report["table"], "rowsAdded": report["rows_added"],
                "noteCount": report["note_count"]}

    @Slot(str, result="QVariantMap")
    def selectTable(self, table: str) -> dict:  # noqa: N802
        if self._storage is None:
            return {"ok": False, "error": "Open a database first."}
        if table not in self._defaulted:
            self._defaulted.add(table)
            if table not in self._filters:
                try:
                    default = views.default_view(self._storage, table)
                except JubakoError:
                    default = None
                if default:
                    if default.get("filter"):
                        self._filters[table] = default["filter"]
                    if default.get("sort"):
                        self._sorts[table] = default["sort"]
                    self._view_names[table] = default["name"]
        where = self._filters.get(table)
        try:
            page = self._storage.list_rows(table, limit=PAGE_SIZE, where=where, sort=self._sorts.get(table))
        except JubakoError:
            # A filter or sort that no longer fits (its field was renamed or deleted) is dropped, not fatal.
            self._filters.pop(table, None)
            self._sorts.pop(table, None)
            where = None
            try:
                page = self._storage.list_rows(table, limit=PAGE_SIZE)
            except JubakoError as error:
                return {"ok": False, "error": str(error)}
        self._rows.load(page)
        self._current_table = table
        self._filter = page.get("filter")
        self._sort = list(page.get("sort") or [])
        self._all_rows = page.get("total_all", page["total"])
        self._fields = [dict(field) for field in page["fields"]]
        try:
            form = form_for(self._storage, table)
            kinds = {f["name"]: f["type"] for f in self._fields}
            self._form_fields = [
                {"name": name, "label": form["labels"].get(name, name), "type": kinds[name]}
                for name in form["fields"] if name in kinds
            ]
            self._form_title = form["title"]
        except JubakoError:
            self._form_fields = list(self._fields)
            self._form_title = table
        self._shown = len(page["rows"])
        self._total = page["total"]
        self.tableChanged.emit()
        return {"ok": True, "shown": self._shown, "total": self._total}

    # -- rows: add, change, delete ------------------------------------------
    @Slot(int, "QVariantMap", result="QVariantMap")
    def saveRow(self, row_id: int, values: dict) -> dict:  # noqa: N802
        """Write one record from the form. `row_id` 0 means a new row."""
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        clean = {name: _from_qml(value) for name, value in dict(values).items()}
        try:
            if int(row_id) > 0:
                self._storage.update_row(self._current_table, int(row_id), clean)
                saved = int(row_id)
            else:
                saved = int(self._storage.add_row(self._current_table, clean) or 0)
        except (ValueError, TypeError) as error:
            return {"ok": False, "error": _value_words(error, self._fields, clean)}
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._refresh_tables(select=self._current_table)
        return {"ok": True, "rowId": saved, "rowIndex": self._rows.rowIndexOf(saved)}

    @Slot(int, result="QVariantMap")
    def deleteRow(self, row_id: int) -> dict:  # noqa: N802
        if self._storage is None or not self._current_table:
            return {"ok": False, "error": "Pick a table first."}
        try:
            gone = self._storage.delete_row(self._current_table, int(row_id))
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._refresh_tables(select=self._current_table)
        if gone:
            self.message.emit("Row deleted.")
        return {"ok": bool(gone), "error": "" if gone else "That row was already gone."}

    def _edit_cell(self, row_id: int, field: str, value: Any) -> bool:
        """A cell typed into in the grid."""
        result = self.saveRow(int(row_id), {field: value})
        if not result["ok"]:
            self.message.emit(result["error"])
        return bool(result["ok"])

    @Slot()
    def refresh(self) -> None:
        if self._storage is not None:
            self._refresh_tables(select=self._current_table)

    @Slot()
    def closeDatabase(self) -> None:  # noqa: N802
        if self._storage is not None:
            try:
                self._storage.close()
            except Exception:  # noqa: BLE001 - a stale handle must not stop us
                pass
        self._storage = None
        self._tables = []
        self._current_table = ""
        self._shown = self._total = 0
        self._filters = {}
        self._filter = None
        self._sorts = {}
        self._sort = []
        self._view_names = {}
        self._defaulted = set()
        self._rows.clear()
        self.tablesChanged.emit()
        self.tableChanged.emit()
        self.databaseChanged.emit()

    # -- inside --------------------------------------------------------------
    def _adopt(self, storage: Storage) -> None:
        if self._storage is not None:
            try:
                self._storage.close()
            except Exception:  # noqa: BLE001
                pass
        self._storage = storage
        self._filters = {}
        self._filter = None
        self._sorts = {}
        self._sort = []
        self._view_names = {}
        self._defaulted = set()
        info = storage.describe()
        catalog.remember(
            title=info.title,
            backend=info.backend,
            path=info.location if info.backend == SQLITE else "",
            where="" if info.backend == SQLITE else info.location,
        )
        self.databaseChanged.emit()
        self._refresh_tables()

    def _refresh_tables(self, *, select: str = "") -> None:
        assert self._storage is not None
        tables = []
        for name in self._storage.list_tables():
            try:
                info = self._storage.describe_table(name)
                tables.append({"name": name, "rows": info.row_count})
            except JubakoError:
                tables.append({"name": name, "rows": 0})
        self._tables = tables
        self.tablesChanged.emit()
        names = [t["name"] for t in tables]
        if select and select in names:
            self.selectTable(select)
        elif names:
            self.selectTable(names[0])
        else:
            self._rows.clear()
            self._current_table = ""
            self._filter = None
            self._sort = []
            self._shown = self._total = self._all_rows = 0
            self.tableChanged.emit()


def _from_qml(value: Any) -> Any:
    """QML hands strings and booleans; blanks mean "no value"."""
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def _value_words(error: Exception, fields: list[dict[str, Any]], values: dict[str, Any]) -> str:
    """Say which field did not fit, in words, instead of a Python error."""
    kinds = {"integer": "a whole number", "real": "a number", "date": "a date like 2024-01-31",
             "boolean": "yes or no"}
    for field in fields:
        if field["name"] in values and values[field["name"]] is not None:
            try:
                from jubako.fields import coerce

                coerce(values[field["name"]], field["type"])
            except (ValueError, TypeError):
                want = kinds.get(field["type"], "words")
                return f"{field['label']} needs {want}. \u201c{values[field['name']]}\u201d does not fit."
    return str(error)


def _parse_where(backend: str, where: str) -> dict[str, str]:
    """Turn the remembered location back into connection fields (no password)."""
    fields = {"host": "", "port": "", "database": "", "user": ""}
    if backend == "postgres":
        if "://" in where:
            fields["url"] = where.replace(":***@", "@")
            return fields
        for chunk in where.split():
            key, _, value = chunk.partition("=")
            if key == "dbname":
                fields["database"] = value
            elif key in fields:
                fields[key] = value
        return fields
    # mysql: user@host:port/database
    user, _, rest = where.rpartition("@")
    fields["user"] = user
    hostport, _, database = rest.partition("/")
    host, _, port = hostport.partition(":")
    fields.update(host=host, port=port, database=database)
    return fields
