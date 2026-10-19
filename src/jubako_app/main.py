"""Start the window: the smallest host that runs QML on Omarchy.

    jubako-app                         # the home screen
    jubako-app ~/Documents/pets.jubadb  # open a database straight away
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from jubako import __version__

from .about import AppInfo, icon_file
from .bridge import Bridge
from .report_bridge import Report, ReportImageProvider
from .theme import Theme

QML_DIR = Path(__file__).resolve().parent / "qml"
APP_ID = "jubako"


def make_app(argv: list[str]) -> QApplication:
    # Fusion is the one built-in Qt Quick style that paints from the palette,
    # which is how the Omarchy theme colours reach every control.
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Fusion")
    QQuickStyle.setStyle(os.environ["QT_QUICK_CONTROLS_STYLE"])
    # QApplication rather than QGuiApplication only because the system print
    # dialog is a widget. The UI itself is all QML.
    # On X11, Qt names the window's WM_CLASS instance after argv[0], which is
    # `__main__.py` or wherever the AppImage lives. Docks match it against the
    # .desktop file's StartupWMClass, so call it by the app id instead.
    app = QApplication([APP_ID, *argv[1:]])
    app.setApplicationName("Jubako")
    app.setApplicationDisplayName("Jubako")
    app.setOrganizationName("Nine Point Labs")
    app.setOrganizationDomain("ninepointlabs.com")
    app.setApplicationVersion(__version__)
    # On Wayland this is the app id Hyprland sees, so it must match the .desktop name.
    app.setDesktopFileName(APP_ID)
    # Installed packages put the icon in the theme; a source checkout or the AppImage has a file.
    icon = icon_file()
    app.setWindowIcon(QIcon.fromTheme(APP_ID, QIcon(str(icon)) if icon else QIcon()))
    return app


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = make_app(argv)
    theme = Theme(app)
    bridge = Bridge()
    provider = ReportImageProvider()
    report = Report(bridge.storage, provider)
    report.message.connect(bridge.message)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("report", provider)
    engine.rootContext().setContextProperty("Bridge", bridge)
    engine.rootContext().setContextProperty("Report", report)
    engine.rootContext().setContextProperty("Theme", theme)
    engine.rootContext().setContextProperty("AppInfo", AppInfo(engine))
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        print("Jubako could not load its window.", file=sys.stderr)
        return 1

    for arg in argv[1:]:
        if not arg.startswith("-"):
            result = bridge.openDatabase("sqlite", arg, {})
            if not result["ok"]:
                bridge.message.emit(result["error"])
            break

    code = app.exec()
    bridge.closeDatabase()
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
