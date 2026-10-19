"""Omarchy's colours, read from the active theme so the window matches the desktop.

`omarchy theme set` writes the chosen theme to
`~/.local/state/omarchy/current/theme/colors.toml`. We read that file and build
a Qt palette from it.

Following a theme change while the window is open needs care: theme-set does
`rm -rf current/theme` and then `mv theme.next current/theme`, so a watch on
`colors.toml` (or on the `theme` directory) goes stale the moment the theme
changes. So we watch the parent, `~/.local/state/omarchy/current/`, which
lives on, plus `theme.name` (rewritten in place), and re-arm the inner watches
after every change. Events come in bursts, so a short timer collects them and
the colours are read once, after the new directory is in place.

When the file is missing (not on Omarchy, or a very old install) a plain
palette is used instead: dark, or light when the desktop says it prefers light
(the freedesktop `color-scheme` setting, which Qt reads for us). Older Omarchy
installs kept the theme under `~/.config/omarchy/current/`, so that is looked at
too. Nothing is watched that does not exist.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from PySide6.QtCore import Property, QFileSystemWatcher, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette

FALLBACK = {
    "mode": "dark",
    "accent": "#7daea3",
    "selection": "#504945",
    "muted": "#665c54",
    "background": "#282828",
    "dark_background": "#1e1e1e",
    "darker_background": "#161616",
    "lighter_background": "#3c3836",
    "foreground": "#d4be98",
    "dark_foreground": "#7c6f64",
    "light_foreground": "#bdae93",
    "bright_foreground": "#d4be98",
    "red": "#ea6962",
    "yellow": "#d8a657",
    "green": "#a9b665",
    "blue": "#7daea3",
}

LIGHT_FALLBACK = {
    "mode": "light",
    "accent": "#3d7a70",
    "selection": "#d5c4a1",
    "muted": "#a89984",
    "background": "#fbf1c7",
    "dark_background": "#f2e5bc",
    "darker_background": "#ebdbb2",
    "lighter_background": "#f9f5d7",
    "foreground": "#3c3836",
    "dark_foreground": "#7c6f64",
    "light_foreground": "#504945",
    "bright_foreground": "#282828",
    "red": "#c14a4a",
    "yellow": "#b47109",
    "green": "#6c782e",
    "blue": "#45707a",
}

COLOR_KEYS = tuple(key for key in FALLBACK if key != "mode")


def current_dir() -> Path:
    """`~/.local/state/omarchy/current/` — the one path that survives a theme change.

    Before Omarchy moved it, this lived at `~/.config/omarchy/current/`; that is
    used only when the new one is absent and the old one is there.
    """
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    current = Path(base) / "omarchy" / "current"
    if not current.exists():
        config = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        legacy = Path(config) / "omarchy" / "current"
        if (legacy / "theme").exists():
            return legacy
    return current


def system_fallback(app: QGuiApplication | None) -> dict[str, str]:
    """The palette to use without an Omarchy theme: light if the desktop asks for light."""
    if app is not None and app.styleHints().colorScheme() == Qt.ColorScheme.Light:
        return LIGHT_FALLBACK
    return FALLBACK


def theme_dir() -> Path:
    return current_dir() / "theme"


def colors_file() -> Path:
    override = os.environ.get("JUBAKO_THEME_FILE")
    return Path(override) if override else theme_dir() / "colors.toml"


def load_colors(path: Path | None = None, fallback: dict[str, str] | None = None) -> dict[str, str]:
    """The theme's colours, with the fallback filling any gap."""
    path = path or colors_file()
    colors = dict(fallback or FALLBACK)
    try:
        data = tomllib.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return colors
    for key in FALLBACK:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            colors[key] = value.strip()
    return colors


def build_palette(colors: dict[str, str]) -> QPalette:
    """Turn Omarchy colours into the palette Qt Quick Controls (Fusion) paints with."""
    dark = colors.get("mode", "dark") != "light"
    c = {key: QColor(value) for key, value in colors.items() if key != "mode"}
    window = c["background"] if dark else c["dark_background"]
    base = c["dark_background"] if dark else c["background"]

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.WindowText, c["foreground"])
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.AlternateBase, c["lighter_background"] if dark else c["dark_background"])
    palette.setColor(QPalette.ColorRole.Text, c["foreground"])
    palette.setColor(QPalette.ColorRole.PlaceholderText, c["dark_foreground"])
    palette.setColor(QPalette.ColorRole.Button, c["lighter_background"])
    palette.setColor(QPalette.ColorRole.ButtonText, c["foreground"])
    palette.setColor(QPalette.ColorRole.BrightText, c["bright_foreground"])
    palette.setColor(QPalette.ColorRole.Highlight, c["accent"])
    palette.setColor(QPalette.ColorRole.HighlightedText, c["background"] if dark else QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, c["blue"])
    palette.setColor(QPalette.ColorRole.ToolTipBase, c["lighter_background"])
    palette.setColor(QPalette.ColorRole.ToolTipText, c["foreground"])
    palette.setColor(QPalette.ColorRole.Light, c["lighter_background"])
    palette.setColor(QPalette.ColorRole.Midlight, c["lighter_background"])
    palette.setColor(QPalette.ColorRole.Mid, c["muted"])
    palette.setColor(QPalette.ColorRole.Dark, c["darker_background"])
    palette.setColor(QPalette.ColorRole.Shadow, c["darker_background"])
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.WindowText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, c["dark_foreground"])
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, window)
    return palette


class Theme(QObject):
    """What QML sees: the colours as properties, and a signal when they change."""

    changed = Signal()

    #: How long to wait after the last file event before reading the theme.
    SETTLE_MS = 150

    def __init__(self, app: QGuiApplication | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._app = app
        # Only without an Omarchy theme does the desktop's light/dark choice count. Asked
        # once, before apply() pins Qt's colour scheme to whatever we pick.
        self._fallback = FALLBACK if colors_file().exists() else system_fallback(app)
        self._colors = load_colors(fallback=self._fallback)
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(self.SETTLE_MS)
        self._settle.timeout.connect(self._reload)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._poke)
        self._watcher.directoryChanged.connect(self._poke)
        self._watch()
        self.apply()

    def watched(self) -> list[str]:
        return sorted(self._watcher.files() + self._watcher.directories())

    def _watch(self) -> None:
        """(Re-)arm the watches. Paths that vanished are dropped, ones that exist are added."""
        if os.environ.get("JUBAKO_THEME_FILE"):
            wanted = [colors_file(), colors_file().parent]
        else:
            current = current_dir()
            wanted = [current, current / "theme.name", theme_dir(), colors_file()]
        wanted_text = {str(p) for p in wanted if p.exists()}
        stale = [p for p in self._watcher.files() + self._watcher.directories() if p not in wanted_text]
        if stale:
            self._watcher.removePaths(stale)
        have = set(self._watcher.files() + self._watcher.directories())
        missing = [p for p in wanted_text if p not in have]
        if missing:
            self._watcher.addPaths(missing)

    @Slot(str)
    def _poke(self, _path: str = "") -> None:
        # rm -rf + mv arrive as several events; wait for the dust to settle.
        self._settle.start()

    @Slot()
    def _reload(self) -> None:
        self._watch()
        fresh = load_colors(fallback=self._fallback)
        if not colors_file().exists():
            # Mid-swap: the new directory is not there yet. Look again shortly.
            self._settle.start()
            return
        if fresh != self._colors:
            self._colors = fresh
            self.apply()
            self.changed.emit()

    def apply(self) -> None:
        if self._app is not None:
            self._app.setPalette(build_palette(self._colors))
            # Qt Quick's Fusion style picks its palette from the colour scheme, not from
            # the application palette, so tell Qt which way the Omarchy theme leans.
            # Main.qml binds the window palette to these colours as well.
            scheme = Qt.ColorScheme.Dark if self.isDark else Qt.ColorScheme.Light
            self._app.styleHints().setColorScheme(scheme)

    def color(self, key: str) -> str:
        return self._colors.get(key, FALLBACK.get(key, "#000000"))

    @Property(bool, notify=changed)
    def isDark(self) -> bool:  # noqa: N802 - QML property name
        return self._colors.get("mode", "dark") != "light"

    @Property(str, notify=changed)
    def window(self) -> str:
        """The window background: what `palette.window` would be, but live."""
        return self.color("background") if self.isDark else self.color("dark_background")

    @Property(str, notify=changed)
    def base(self) -> str:
        """Where rows and text fields sit."""
        return self.color("dark_background") if self.isDark else self.color("background")

    @Property(str, notify=changed)
    def alternateBase(self) -> str:  # noqa: N802
        return self.color("lighter_background") if self.isDark else self.color("dark_background")

    @Property(str, notify=changed)
    def uiFont(self) -> str:  # noqa: N802
        return QFont().family() or "sans-serif"

    @Property(str, notify=changed)
    def monoFont(self) -> str:  # noqa: N802
        return os.environ.get("JUBAKO_MONO_FONT", "JetBrainsMono Nerd Font")

    @Property(str, notify=changed)
    def accent(self) -> str:  # noqa: N802
        return self.color("accent")

    @Property(str, notify=changed)
    def selection(self) -> str:  # noqa: N802
        return self.color("selection")

    @Property(str, notify=changed)
    def muted(self) -> str:  # noqa: N802
        return self.color("muted")

    @Property(str, notify=changed)
    def background(self) -> str:  # noqa: N802
        return self.color("background")

    @Property(str, notify=changed)
    def darkBackground(self) -> str:  # noqa: N802
        return self.color("dark_background")

    @Property(str, notify=changed)
    def darkerBackground(self) -> str:  # noqa: N802
        return self.color("darker_background")

    @Property(str, notify=changed)
    def lighterBackground(self) -> str:  # noqa: N802
        return self.color("lighter_background")

    @Property(str, notify=changed)
    def foreground(self) -> str:  # noqa: N802
        return self.color("foreground")

    @Property(str, notify=changed)
    def darkForeground(self) -> str:  # noqa: N802
        return self.color("dark_foreground")

    @Property(str, notify=changed)
    def lightForeground(self) -> str:  # noqa: N802
        return self.color("light_foreground")

    @Property(str, notify=changed)
    def brightForeground(self) -> str:  # noqa: N802
        return self.color("bright_foreground")

    @Property(str, notify=changed)
    def highlightedText(self) -> str:  # noqa: N802
        """Text on the accent colour."""
        return self.color("background") if self.isDark else "#ffffff"

    @Property(str, notify=changed)
    def red(self) -> str:  # noqa: N802
        return self.color("red")

    @Property(str, notify=changed)
    def yellow(self) -> str:  # noqa: N802
        return self.color("yellow")

    @Property(str, notify=changed)
    def green(self) -> str:  # noqa: N802
        return self.color("green")

    @Property(str, notify=changed)
    def blue(self) -> str:  # noqa: N802
        return self.color("blue")
