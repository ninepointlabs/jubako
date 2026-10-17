"""What the About dialog says: version, who made it, licence, support, toolkit versions."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import PySide6
from PySide6.QtCore import Property, QObject, QUrl, Slot, qVersion
from PySide6.QtGui import QGuiApplication

from jubako import __version__

APP_NAME = "Jubako"
TAGLINE = "A simple desktop database for Omarchy, in the spirit of Microsoft Access."
ORGANIZATION = "Nine Point Labs"
SUPPORT_EMAIL = "help@ninepointlabs.com"
CREATED = "September 2026"  # first commit: 2026-09-21
LICENSE_NAME = "MIT License"
COPYRIGHT = "© 2026 Nine Point Labs"

HERE = Path(__file__).resolve().parent
LICENSE_FILE = HERE / "assets" / "LICENSE.txt"
# A source checkout has the icon in packaging/; the packages put it in the icon theme.
ICON_FILES = (
    HERE.parents[1] / "packaging" / "jubako.svg",
    Path("/usr/share/icons/hicolor/scalable/apps/jubako.svg"),
)


def python_version() -> str:
    return sys.version.split()[0]


class AppInfo(QObject):
    """Constant facts for QML's About dialog."""

    name = Property(str, lambda self: APP_NAME, constant=True)
    tagline = Property(str, lambda self: TAGLINE, constant=True)
    version = Property(str, lambda self: __version__, constant=True)
    organization = Property(str, lambda self: ORGANIZATION, constant=True)
    supportEmail = Property(str, lambda self: SUPPORT_EMAIL, constant=True)
    created = Property(str, lambda self: CREATED, constant=True)
    license = Property(str, lambda self: LICENSE_NAME, constant=True)
    copyright = Property(str, lambda self: COPYRIGHT, constant=True)
    qtVersion = Property(str, lambda self: qVersion(), constant=True)
    pysideVersion = Property(str, lambda self: PySide6.__version__, constant=True)
    pythonVersion = Property(str, lambda self: python_version(), constant=True)

    @Property(QUrl, constant=True)
    def icon(self) -> QUrl:
        for path in ICON_FILES:
            if path.exists():
                return QUrl.fromLocalFile(str(path))
        return QUrl()

    @Property(str, constant=True)
    def licenseText(self) -> str:
        try:
            text = LICENSE_FILE.read_text(encoding="utf-8")
        except OSError:
            return f"{LICENSE_NAME}, {COPYRIGHT}"
        # One line per paragraph, so it wraps to the dialog's width.
        return "\n\n".join(" ".join(p.split()) for p in text.split("\n\n") if p.strip())

    @Property(str, constant=True)
    def details(self) -> str:
        """Version details to paste into a support email."""
        return (
            f"{APP_NAME} {__version__}\n"
            f"Qt {qVersion()}, PySide6 {PySide6.__version__}, Python {python_version()}\n"
            f"{os.environ.get('XDG_CURRENT_DESKTOP', 'unknown desktop')}, "
            f"{QGuiApplication.platformName()}"
        )

    @Slot(str)
    def copy(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
