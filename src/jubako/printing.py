"""Draw a report onto pages: PDF, the system printer, or a preview picture.

This is the one part of the core that needs Qt (PySide6), and only when a
report is actually rendered. The same `ReportDocument` paints every target,
so what you preview is what you print.

Units are points (1/72 inch) throughout; the painter is scaled to match.
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
from typing import Any

from .errors import JubakoError
from .reports import fit_columns, page_points

MM_TO_PT = 72.0 / 25.4
CELL_PAD = 4.0
MIN_COLUMN_PT = 36.0


def _qt():
    try:
        from PySide6 import QtCore, QtGui  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise JubakoError(
            "Making a PDF or printing needs Qt (the 'pyside6' package)."
        ) from exc
    return QtCore, QtGui


def ensure_gui_app():
    """A QGuiApplication must exist to measure fonts. Make an offscreen one if needed."""
    QtCore, QtGui = _qt()
    app = QtGui.QGuiApplication.instance()
    if app is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QtGui.QGuiApplication(sys.argv[:1] or ["jubako"])
    return app


class ReportDocument:
    """A laid-out report: knows its pages and how to paint each one.

    It prints *lines*: rows, and when the report groups or totals, group
    headings, subtotals and a grand total (see `reports.report_lines`). Plain
    rows of text may be given instead, for a simple list.
    """

    def __init__(
        self,
        spec: dict[str, Any],
        rows: list[list[str]] | None = None,
        *,
        lines: list[dict[str, Any]] | None = None,
    ) -> None:
        ensure_gui_app()
        QtCore, QtGui = _qt()
        self.spec = spec
        if lines is None:
            lines = [{"kind": "row", "cells": list(row)} for row in (rows or [])]
        self.labels = list(spec["labels"])
        if spec.get("show_row_numbers"):
            self.labels = ["#"] + self.labels
            number = 0
            numbered = []
            for line in lines:
                if line["kind"] == "row":
                    number += 1
                    line = {**line, "cells": [str(number)] + list(line["cells"])}
                elif "cells" in line:
                    line = {**line, "cells": [""] + list(line["cells"])}
                numbered.append(line)
            lines = numbered
        self.lines = lines
        #: Just the rows, as text (what the older callers and tests read).
        self.rows = [line["cells"] for line in lines if line["kind"] == "row"]

        self.page_w, self.page_h = page_points(spec)
        margin = spec["margins_mm"] * MM_TO_PT
        self.content = QtCore.QRectF(margin, margin, self.page_w - 2 * margin, self.page_h - 2 * margin)

        # Pixel sizes, not point sizes: the painter is scaled so one unit is one
        # point on every target, and a pixel-size font ignores the device's DPI.
        # So "10pt" measures and paints the same on paper, in a PDF and on screen.
        self.font = QtGui.QFont()
        self.font.setPixelSize(int(round(spec["font_pt"])))
        self.bold = QtGui.QFont(self.font)
        self.bold.setBold(True)
        self.title_font = QtGui.QFont(self.bold)
        self.title_font.setPixelSize(int(round(spec["font_pt"] + 5)))
        self.small = QtGui.QFont(self.font)
        self.small.setPixelSize(int(round(max(6.0, spec["font_pt"] - 2))))

        self._layout()

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def _subtitles(self) -> list[str]:
        """The small lines under the title: which rows, and in what order."""
        out = []
        if self.spec.get("view"):
            out.append("View: " + self.spec["view"])
        if self.spec.get("filter_words"):
            out.append("Only rows where " + self.spec["filter_words"])
        if self.spec.get("sort_words"):
            out.append("Sorted by " + self.spec["sort_words"])
        return out

    # -- layout ------------------------------------------------------------
    def _layout(self) -> None:
        QtCore, QtGui = _qt()
        metrics = QtGui.QFontMetricsF(self.font)
        bold_metrics = QtGui.QFontMetricsF(self.bold)
        small_metrics = QtGui.QFontMetricsF(self.small)
        count = len(self.labels)
        natural = [bold_metrics.horizontalAdvance(label) + 2 * CELL_PAD for label in self.labels]
        minimum = [min(natural[i], MIN_COLUMN_PT) for i in range(count)]
        measured = 0
        for line in self.lines:
            if "cells" not in line:
                continue
            measure = metrics if line["kind"] == "row" else bold_metrics
            for i, text in enumerate(line["cells"][:count]):
                natural[i] = max(natural[i], measure.horizontalAdvance(text) + 2 * CELL_PAD)
                longest_word = max((measure.horizontalAdvance(w) for w in text.split()), default=0.0)
                minimum[i] = max(minimum[i], min(longest_word + 2 * CELL_PAD, 120.0))
            measured += 1
            if measured >= 2000:
                break
        self.widths = fit_columns(natural, minimum, self.content.width(), fit=self.spec["fit_to_width"])
        self.table_width = sum(self.widths)

        self.line_h = metrics.height()
        self.title_h = QtGui.QFontMetricsF(self.title_font).height() + 8
        self.subtitle_h = (small_metrics.height() + 4) * len(self._subtitles())
        self.page_header_h = (small_metrics.height() + 6) if self.spec.get("header_text") else 0.0
        self.header_h = bold_metrics.height() + 2 * CELL_PAD
        self.footer_h = small_metrics.height() + 6

        # Line heights: wrapped text, so a long cell makes its row taller.
        self.line_heights: list[float] = []
        flags = int(QtCore.Qt.TextFlag.TextWordWrap)
        for line in self.lines:
            if line["kind"] == "group":
                self.line_heights.append(bold_metrics.height() + 2 * CELL_PAD + 4)
                continue
            measure = metrics if line["kind"] == "row" else bold_metrics
            tallest = self.line_h
            for i, text in enumerate(line["cells"][:count]):
                if not text:
                    continue
                rect = QtCore.QRectF(0, 0, max(1.0, self.widths[i] - 2 * CELL_PAD), 10000)
                tallest = max(tallest, measure.boundingRect(rect, flags, text).height())
            label = line.get("label")
            if label:
                tallest = max(tallest, bold_metrics.height())
                if line["kind"] == "total":
                    tallest += bold_metrics.height()  # the label sits on its own line above the figures
            self.line_heights.append(tallest + 2 * CELL_PAD)

        # Pages: which lines go on which page. The title is on page one only.
        self.pages: list[tuple[int, int]] = []
        start = 0
        first = True
        total = len(self.lines)
        while start < total or first:
            top = (self.content.top() + self.page_header_h
                   + ((self.title_h + self.subtitle_h) if first else 0) + self.header_h)
            bottom = self.content.bottom() - self.footer_h
            end = start
            used = top
            while end < total and used + self.line_heights[end] <= bottom:
                used += self.line_heights[end]
                end += 1
            # A group heading never sits alone at the foot of a page.
            if end - 1 > start and end < total and self.lines[end - 1]["kind"] == "group":
                end -= 1
            if end == start and start < total:
                end = start + 1  # a single line taller than the page still goes somewhere
            self.pages.append((start, end))
            start = end
            first = False

    @property
    def page_count(self) -> int:
        return len(self.pages)

    # -- painting ------------------------------------------------------------
    def paint_page(self, painter, page_index: int) -> None:
        """Paint one page. The painter must already be in points."""
        QtCore, QtGui = _qt()
        Qt = QtCore.Qt
        start, end = self.pages[page_index]
        fg = QtGui.QColor("#111111")
        grey = QtGui.QColor("#555555")
        rule = QtGui.QColor("#9a9a9a")
        band = QtGui.QColor("#e6e6e6")
        stripe = QtGui.QColor("#f4f4f4")
        group_band = QtGui.QColor("#eeeeee")
        painter.setPen(QtGui.QPen(fg))
        left_middle = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        x0 = self.content.left()
        y = self.content.top()
        if self.page_header_h:
            painter.setFont(self.small)
            painter.setPen(QtGui.QPen(grey))
            painter.drawText(QtCore.QRectF(x0, y, self.content.width(), self.page_header_h),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), self.spec["header_text"])
            painter.setPen(QtGui.QPen(fg))
            y += self.page_header_h
        if page_index == 0:
            painter.setFont(self.title_font)
            painter.drawText(QtCore.QRectF(x0, y, self.content.width(), self.title_h), left_middle, self.spec["title"])
            y += self.title_h
            subtitles = self._subtitles()
            if subtitles:
                painter.setFont(self.small)
                painter.setPen(QtGui.QPen(grey))
                each = self.subtitle_h / len(subtitles)
                for text in subtitles:
                    painter.drawText(QtCore.QRectF(x0, y, self.content.width(), each), left_middle, text)
                    y += each
                painter.setPen(QtGui.QPen(fg))

        # Header band
        painter.fillRect(QtCore.QRectF(x0, y, self.table_width, self.header_h), band)
        painter.setFont(self.bold)
        x = x0
        for width, label in zip(self.widths, self.labels):
            painter.drawText(QtCore.QRectF(x + CELL_PAD, y, max(1.0, width - 2 * CELL_PAD), self.header_h),
                             left_middle, label)
            x += width
        painter.setPen(QtGui.QPen(rule, 0.8))
        painter.drawLine(QtCore.QPointF(x0, y + self.header_h), QtCore.QPointF(x0 + self.table_width, y + self.header_h))
        y += self.header_h

        flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap)
        stripe_index = 0
        for index in range(start, end):
            line = self.lines[index]
            height = self.line_heights[index]
            kind = line["kind"]
            if kind == "group":
                stripe_index = 0
                painter.fillRect(QtCore.QRectF(x0, y + 4, self.table_width, height - 4), group_band)
                painter.setFont(self.bold)
                painter.setPen(QtGui.QPen(fg))
                inner = QtCore.QRectF(x0 + CELL_PAD, y + 4, self.table_width - 2 * CELL_PAD, height - 4)
                painter.drawText(inner, left_middle, line["text"])
                if line.get("count"):
                    painter.setFont(self.small)
                    painter.setPen(QtGui.QPen(grey))
                    painter.drawText(inner, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), line["count"])
                y += height
                continue

            if kind == "row":
                if stripe_index % 2 == 1:
                    painter.fillRect(QtCore.QRectF(x0, y, self.table_width, height), stripe)
                stripe_index += 1
                painter.setFont(self.font)
            else:
                painter.setPen(QtGui.QPen(rule, 0.8 if kind == "total" else 0.4))
                painter.drawLine(QtCore.QPointF(x0, y), QtCore.QPointF(x0 + self.table_width, y))
                painter.setFont(self.bold)
            painter.setPen(QtGui.QPen(fg))

            cell_top = y
            label = line.get("label") or ""
            if kind == "total" and label:
                painter.setPen(QtGui.QPen(grey))
                painter.drawText(QtCore.QRectF(x0 + CELL_PAD, y + CELL_PAD, self.table_width - 2 * CELL_PAD, self.line_h),
                                 int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), label)
                painter.setPen(QtGui.QPen(fg))
                cell_top = y + QtGui.QFontMetricsF(self.bold).height()
            elif kind == "subtotal" and label:
                # The label goes in the first empty cell, if there is one.
                cells = line["cells"]
                for i, text in enumerate(cells):
                    if not text:
                        line = {**line, "cells": cells[:i] + [label] + cells[i + 1:]}
                        break
            x = x0
            for width, text in zip(self.widths, line["cells"]):
                if text:
                    painter.drawText(
                        QtCore.QRectF(x + CELL_PAD, cell_top + CELL_PAD, max(1.0, width - 2 * CELL_PAD),
                                      height - (cell_top - y) - 2 * CELL_PAD),
                        flags,
                        text,
                    )
                x += width
            if kind == "row":
                painter.setPen(QtGui.QPen(rule, 0.4))
                painter.drawLine(QtCore.QPointF(x0, y + height), QtCore.QPointF(x0 + self.table_width, y + height))
            y += height

        if not self.rows and page_index == 0:
            painter.setFont(self.font)
            painter.setPen(QtGui.QPen(fg))
            painter.drawText(
                QtCore.QRectF(x0, y + 8, self.content.width(), self.line_h * 2),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                "No rows to show." if self.spec.get("filter_words") else "This table has no rows yet.",
            )

        # Footer
        painter.setFont(self.small)
        painter.setPen(QtGui.QPen(grey))
        footer = QtCore.QRectF(x0, self.content.bottom() - self.footer_h, self.content.width(), self.footer_h)
        left = self.spec.get("footer_text") or self.spec["title"]
        painter.drawText(footer, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom),
                         f"{left}  ·  {_dt.date.today().isoformat()}")
        painter.drawText(footer, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom),
                         f"Page {page_index + 1} of {self.page_count}")

    # -- targets ------------------------------------------------------------
    def _page_layout(self):
        QtCore, QtGui = _qt()
        size_id = {"letter": QtGui.QPageSize.PageSizeId.Letter, "a4": QtGui.QPageSize.PageSizeId.A4,
                   "legal": QtGui.QPageSize.PageSizeId.Legal}[self.spec["page_size"]]
        orientation = (QtGui.QPageLayout.Orientation.Landscape if self.spec["orientation"] == "landscape"
                       else QtGui.QPageLayout.Orientation.Portrait)
        # Margins are painted by us, so the device gets none.
        return QtGui.QPageLayout(QtGui.QPageSize(size_id), orientation, QtCore.QMarginsF(0, 0, 0, 0),
                                 QtGui.QPageLayout.Unit.Point)

    def paint_to_device(self, device) -> int:
        """Paint every page onto a paged device (QPdfWriter or QPrinter) already set up."""
        QtCore, QtGui = _qt()
        painter = QtGui.QPainter()
        if not painter.begin(device):
            raise JubakoError("Could not start drawing on that printer or file.")
        try:
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
            # Device units -> points.
            scale = device.logicalDpiX() / 72.0
            for index in range(self.page_count):
                if index > 0:
                    device.newPage()
                painter.resetTransform()
                painter.scale(scale, scale)
                self.paint_page(painter, index)
        finally:
            painter.end()
        return self.page_count

    def write_pdf(self, path: str) -> int:
        QtCore, QtGui = _qt()
        writer = QtGui.QPdfWriter(path)
        writer.setTitle(self.spec["title"])
        writer.setCreator("Jubako")
        writer.setPageLayout(self._page_layout())
        writer.setResolution(300)
        return self.paint_to_device(writer)

    def print_to(self, printer) -> int:
        """`printer` is a QPrinter the caller (usually a print dialog) set up."""
        printer.setPageLayout(self._page_layout())
        printer.setDocName(self.spec["title"])
        return self.paint_to_device(printer)

    def preview_image(self, page_index: int, width_px: int = 900):
        """One page as a QImage, for the preview on screen."""
        QtCore, QtGui = _qt()
        scale = width_px / self.page_w
        image = QtGui.QImage(int(self.page_w * scale), int(self.page_h * scale),
                             QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QtGui.QColor("white"))
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
        painter.scale(scale, scale)
        self.paint_page(painter, max(0, min(page_index, self.page_count - 1)))
        painter.end()
        return image
