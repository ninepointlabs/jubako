"""The report designer's back end: build a report, preview it, print it, save it.

`Report` is what the QML dialog talks to. `ReportImageProvider` serves the
preview pages to QML `Image` items as `image://report/<page>?<version>`.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, QObject, QSize, QUrl, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

from jubako import views
from jubako.errors import JubakoError
from jubako.paths import resolve_under_roots
from jubako.printing import ReportDocument
from jubako.reports import (
    PAGE_SIZES,
    delete_report,
    fetch_lines,
    list_reports,
    load_report,
    normalise_spec,
    save_report,
)

PREVIEW_WIDTH = 1000


class ReportImageProvider(QQuickImageProvider):
    """Paints preview pages on demand. The id is `<page>?<version>`."""

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.document: ReportDocument | None = None

    def requestImage(self, image_id: str, size: QSize, requested: QSize) -> QImage:  # noqa: N802
        page = 0
        try:
            page = int(image_id.split("?", 1)[0])
        except ValueError:
            pass
        if self.document is None:
            blank = QImage(10, 10, QImage.Format.Format_ARGB32_Premultiplied)
            blank.fill(0)
            return blank
        width = requested.width() if requested.isValid() and requested.width() > 0 else PREVIEW_WIDTH
        image = self.document.preview_image(page, width)
        if size is not None:
            size.setWidth(image.width())
            size.setHeight(image.height())
        return image


class Report(QObject):
    """One report being designed for the open database."""

    changed = Signal()
    message = Signal(str)

    def __init__(self, get_storage, provider: ReportImageProvider, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._get_storage = get_storage
        self._provider = provider
        self._spec: dict[str, Any] = {}
        self._document: ReportDocument | None = None
        self._error = ""
        self._version = 0

    # -- what the dialog reads ------------------------------------------------
    @Property("QVariantMap", notify=changed)
    def spec(self) -> dict[str, Any]:
        return dict(self._spec)

    @Property(int, notify=changed)
    def pageCount(self) -> int:  # noqa: N802
        return self._document.page_count if self._document else 0

    @Property(int, notify=changed)
    def rowCount(self) -> int:  # noqa: N802
        return self._document.row_count if self._document else 0

    @Property(str, notify=changed)
    def error(self) -> str:
        return self._error

    @Property(int, notify=changed)
    def version(self) -> int:
        return self._version

    @Slot(int, result=str)
    def previewSource(self, page: int) -> str:  # noqa: N802
        return f"image://report/{max(0, page)}?{self._version}"

    @Slot(result="QVariantList")
    def pageSizes(self) -> list[str]:  # noqa: N802
        return list(PAGE_SIZES)

    @Slot(str, result="QVariantList")
    def viewsFor(self, table: str) -> list[dict[str, Any]]:  # noqa: N802
        """A table's saved views, for "From a saved view": name and the rule in words."""
        storage = self._get_storage()
        if storage is None or not table:
            return []
        try:
            return [{"name": v["name"], "words": v.get("words", "")} for v in views.list_views(storage, table)]
        except JubakoError:
            return []

    # -- building --------------------------------------------------------------
    @Slot("QVariantMap", result="QVariantMap")
    def build(self, spec: dict) -> dict:
        """Lay the report out from the dialog's settings. Cheap enough to do live."""
        storage = self._get_storage()
        if storage is None:
            return self._fail("Open a database first.")
        try:
            full = normalise_spec(storage, _clean(dict(spec)))
            document = ReportDocument(full, lines=fetch_lines(storage, full))
        except JubakoError as error:
            return self._fail(str(error))
        self._spec = full
        self._document = document
        self._provider.document = document
        self._error = ""
        self._version += 1
        self.changed.emit()
        return {"ok": True, "pages": document.page_count, "rows": document.row_count}

    def _fail(self, text: str) -> dict:
        self._error = text
        self.changed.emit()
        return {"ok": False, "error": text}

    # -- outputs -------------------------------------------------------------------
    @Slot(str, result="QVariantMap")
    def savePdf(self, url: str) -> dict:  # noqa: N802
        if self._document is None:
            return {"ok": False, "error": "Nothing to save yet."}
        path = QUrl(url).toLocalFile() if QUrl(url).isLocalFile() else url
        try:
            target = resolve_under_roots(path)
            if target.suffix.lower() != ".pdf":
                target = target.with_name(target.name + ".pdf")
            target.parent.mkdir(parents=True, exist_ok=True)
            pages = self._document.write_pdf(str(target))
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self.message.emit(f"Saved {pages} page{'s' if pages != 1 else ''} to {target.name}.")
        return {"ok": True, "file": str(target), "pages": pages}

    @Slot(result="QVariantMap")
    def printReport(self) -> dict:  # noqa: N802
        """The system print dialog, then the same pages the preview shows."""
        if self._document is None:
            return {"ok": False, "error": "Nothing to print yet."}
        try:
            from PySide6.QtPrintSupport import QPrintDialog, QPrinter  # noqa: PLC0415
        except ImportError:
            return {"ok": False, "error": "Printing needs Qt's print support, which is not installed."}
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(self._spec.get("title", "Report"))
        dialog = QPrintDialog(printer)
        dialog.setWindowTitle("Print " + self._spec.get("title", "report"))
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return {"ok": False, "cancelled": True}
        try:
            pages = self._document.print_to(printer)
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self.message.emit(f"Sent {pages} page{'s' if pages != 1 else ''} to {printer.printerName() or 'the printer'}.")
        return {"ok": True, "pages": pages}

    # -- keeping reports in the database ------------------------------------------------
    @Slot(str, result="QVariantMap")
    def keep(self, name: str) -> dict:
        storage = self._get_storage()
        if storage is None or not self._spec:
            return {"ok": False, "error": "Nothing to keep yet."}
        try:
            saved = save_report(storage, {**self._spec, "name": name})
        except JubakoError as error:
            return {"ok": False, "error": str(error)}
        self._spec = saved
        self.changed.emit()
        self.message.emit(f"Kept the report “{saved['name']}”.")
        return {"ok": True, "name": saved["name"]}

    @Slot(result="QVariantList")
    def kept(self) -> list[dict[str, Any]]:
        storage = self._get_storage()
        return list_reports(storage) if storage is not None else []

    @Slot(str, result="QVariantMap")
    def load(self, name: str) -> dict:
        storage = self._get_storage()
        if storage is None:
            return {"ok": False, "error": "Open a database first."}
        spec = load_report(storage, name)
        if spec is None:
            return {"ok": False, "error": f"There is no report called “{name}”."}
        result = self.build(spec)
        result["spec"] = dict(self._spec)
        return result

    @Slot(str, result="QVariantMap")
    def forget(self, name: str) -> dict:
        storage = self._get_storage()
        if storage is None:
            return {"ok": False, "error": "Open a database first."}
        gone = delete_report(storage, name)
        return {"ok": gone, "error": "" if gone else "That report was already gone."}


def _clean(spec: dict[str, Any]) -> dict[str, Any]:
    """QML sends strings for numbers and may include blanks; tidy before checking."""
    out: dict[str, Any] = {}
    for key, value in spec.items():
        if value in ("", None):
            continue
        if key in ("margins_mm", "font_pt"):
            try:
                out[key] = float(value)
            except (TypeError, ValueError):
                continue
        elif key == "columns":
            out[key] = [str(v) for v in value]
        elif key == "filter":
            if isinstance(value, dict) and (value.get("field") or value.get("rules")):
                out[key] = dict(value)
        elif key == "sort":
            out[key] = [dict(item) for item in value if item and item.get("field")]
        elif key == "totals":
            out[key] = {str(name): str(how) for name, how in dict(value).items() if how}
        else:
            out[key] = value
    return out
