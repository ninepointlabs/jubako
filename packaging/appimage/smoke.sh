#!/usr/bin/env bash
# Check a built AppImage the way someone on another distro would meet it.
#
#   packaging/appimage/smoke.sh dist/jubako-<version>-x86_64.AppImage
#
# Runs without FUSE (APPIMAGE_EXTRACT_AND_RUN), so it works in containers and CI.
# Needs what packaging/appimage/apt-packages.txt lists (Xvfb, xdotool, xprop...).

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
image="$(readlink -f "${1:?usage: smoke.sh <AppImage>}")"
export APPIMAGE_EXTRACT_AND_RUN=1
work="$(mktemp -d)"
trap 'kill "${xvfb_pid:-}" 2>/dev/null || true; rm -rf "$work"' EXIT
cd "$work"
failures=0
ok() { echo "ok: $*"; }
fail() { echo "FAIL: $*" >&2; failures=$((failures + 1)); }
# Words that mean something went wrong at start-up (missing plugin, QML module, import...).
problems='error|not installed|cannot|failed|traceback|could not'

"$image" --appimage-extract >/dev/null
appdir="$work/squashfs-root"
python="$appdir/opt/python3.12/bin/python3.12"

echo "== Desktop entry, metainfo and icons inside"
desktop-file-validate "$appdir/jubako.desktop" && desktop-file-validate "$appdir/usr/share/applications/jubako.desktop" \
  && ok "desktop files validate" || fail "desktop-file-validate"
grep -q '^X-AppImage-Version=' "$appdir/jubako.desktop" && ok "X-AppImage-Version set" || fail "no X-AppImage-Version"
if appstreamcli validate --no-net "$appdir/usr/share/metainfo/jubako.appdata.xml"; then
  ok "metainfo validates"
else
  fail "appstreamcli validate"
fi
for size in 16 24 32 48 64 128 256 512; do
  png="$appdir/usr/share/icons/hicolor/${size}x${size}/apps/jubako.png"
  file "$png" | grep -q "PNG image data, $size x $size" || fail "icon $size: $(file -b "$png" 2>&1)"
done
[[ -f "$appdir/usr/share/icons/hicolor/scalable/apps/jubako.svg" && -f "$appdir/jubako.svg" ]] || fail "SVG icon missing"
file -L "$appdir/.DirIcon" | grep -q "PNG image data, 256 x 256" || fail ".DirIcon is not the 256px PNG"
ok "icons: 16-512 PNGs, scalable SVG, root icon, .DirIcon"

echo "== Every QML file compiles against the bundled Qt"
"$python" -I "$here/packaging/appimage/check_qml.py" && ok "QML" || fail "QML imports missing from the bundle"

echo "== Command line, Excel, PDF"
export JUBAKO_ROOTS="$work"  # Jubako only touches files under the home folder unless told otherwise
cp "$here/data/examples/pets.csv" pets.csv
"$image" cli --help >/dev/null && ok "cli --help" || fail "cli --help"
"$image" cli new Demo "$work/demo" >/dev/null
"$image" cli import demo.jubadb pets.csv >/dev/null
"$image" cli tables demo.jubadb | grep -q pets && ok "cli new + import CSV" || fail "cli import CSV"
"$image" cli export demo.jubadb pets pets.xlsx --format xlsx >/dev/null
file pets.xlsx | grep -Eq "Excel|Zip|OOXML" && ok "export Excel (openpyxl bundled)" || fail "export xlsx"
"$image" cli new Again "$work/again" >/dev/null
"$image" cli import again.jubadb pets.xlsx >/dev/null && "$image" cli rows again.jubadb pets | grep -q . \
  && ok "import Excel" || fail "import xlsx"
"$image" cli report demo.jubadb pets pets.pdf --title "All the pets" >report.log 2>&1 || true
if file pets.pdf 2>/dev/null | grep -q "PDF document" && ! grep -Eiq "$problems" report.log; then
  ok "report to PDF"
else
  fail "report to PDF: $(cat report.log)"
fi
"$image" cli backends >backends.txt
grep -qi postgres backends.txt && ok "cli backends" || fail "cli backends"

echo "== MCP server"
reply="$(echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' | "$image" mcp)"
grep -q '"name": "jubako"' <<<"$reply" && ok "mcp initialize" || fail "mcp: $reply"
ln -s "$image" jubako-mcp
reply="$(echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | ./jubako-mcp)"
grep -q import_spreadsheet <<<"$reply" && ok "mcp via a jubako-mcp symlink" || fail "jubako-mcp symlink: $reply"

echo "== Print support"
QT_DEBUG_PLUGINS=1 QT_QPA_PLATFORM=offscreen "$python" -I -c '
from PySide6.QtWidgets import QApplication
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
from PySide6.QtGui import QPainter
app = QApplication(["jubako"])
QPrinterInfo.availablePrinterNames()
printer = QPrinter(QPrinter.PrinterMode.HighResolution)
printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
printer.setOutputFileName("printed.pdf")
painter = QPainter(printer); painter.drawText(100, 100, "Jubako"); painter.end()
' >print.log 2>&1 || true
if grep -q "cupsprintersupport" print.log && ! grep -Eq "Cannot load library.*cups" print.log \
  && file printed.pdf | grep -q PDF; then
  ok "CUPS print plugin loads; QPrinter writes"
else
  fail "print support: $(grep -Ei 'cups|cannot' print.log | head -5)"
fi

echo "== The window, offscreen"
set +e
QT_QPA_PLATFORM=offscreen timeout 8 "$image" >offscreen.log 2>&1
rc=$?
set -e
if [[ $rc == 124 ]] && ! grep -Eiq "$problems" offscreen.log; then
  ok "window starts offscreen"
else
  fail "offscreen window (exit $rc): $(cat offscreen.log)"
fi

echo "== The window on X11 (Xvfb), with no Omarchy, no Hyprland and an empty home"
Xvfb :77 -screen 0 1280x800x24 -nolisten tcp >/dev/null 2>&1 &
xvfb_pid=$!
sleep 1
fresh_home="$(mktemp -d)"
env -i DISPLAY=:77 HOME="$fresh_home" PATH=/usr/bin:/bin APPIMAGE_EXTRACT_AND_RUN=1 LANG=C.UTF-8 \
  "$image" >x11.log 2>&1 &
app_pid=$!
wid="$(DISPLAY=:77 timeout 30 xdotool search --sync --onlyvisible --classname '^jubako$' 2>/dev/null | head -1 || true)"
if [[ -n "$wid" ]]; then
  wm_class="$(DISPLAY=:77 xprop -id "$wid" WM_CLASS)"
  wanted="$(sed -n 's/^StartupWMClass=//p' "$appdir/jubako.desktop")"
  if grep -q "\"$wanted\"" <<<"$wm_class"; then
    ok "WM_CLASS ($wm_class) has StartupWMClass=$wanted"
  elif [[ "${SMOKE_WM_CLASS_WARN_ONLY:-0}" == 1 ]]; then
    echo "warning: WM_CLASS $wm_class does not match StartupWMClass=$wanted (this version predates the fix)"
  else
    fail "WM_CLASS $wm_class does not match StartupWMClass=$wanted"
  fi
  win_pid="$(DISPLAY=:77 xdotool getwindowpid "$wid")"
  leaked="$(tr '\0' '\n' <"/proc/$win_pid/environ" | grep -E '^(LD_LIBRARY_PATH|LD_PRELOAD|PYTHONHOME|PYTHONPATH|QT_PLUGIN_PATH|QML2_IMPORT_PATH|QML_IMPORT_PATH|XDG_DATA_DIRS|SSL_CERT_FILE|TCL_LIBRARY)=' || true)"
  [[ -z "$leaked" ]] && ok "the app's environment (inherited by anything it starts) has nothing from the bundle" \
    || fail "bundle variables leak to child processes: $leaked"
  sleep 2
else
  fail "no window appeared on Xvfb: $(cat x11.log)"
fi
kill "$app_pid" 2>/dev/null || true
pkill -f "$appdir/opt/python3.12" 2>/dev/null || true
wait "$app_pid" 2>/dev/null || true
if grep -Eiq "$problems" x11.log; then fail "X11 run printed: $(cat x11.log)"; else ok "X11 run is quiet (theme fell back, no tracebacks)"; fi
[[ ! -e "$fresh_home/.local/state/omarchy" && ! -e "$fresh_home/.config/omarchy" && ! -e "$fresh_home/.config/hypr" ]] \
  && ok "wrote no Omarchy or Hyprland config" || fail "touched Omarchy/Hyprland config in a fresh home"

echo "== --install-desktop-entry / --remove-desktop-entry"
data="$work/xdg-data"
XDG_DATA_HOME="$data" "$image" --install-desktop-entry
entry="$data/applications/jubako.desktop"
desktop-file-validate "$entry" && ok "installed entry validates" || fail "installed entry does not validate"
grep -qx "Exec=\"$image\" app %f" "$entry" && grep -qx "TryExec=$image" "$entry" \
  && ok "Exec and TryExec point at the AppImage" || fail "Exec/TryExec: $(grep -E '^(Try)?Exec=' "$entry")"
[[ -f "$data/icons/hicolor/256x256/apps/jubako.png" && -f "$data/icons/hicolor/scalable/apps/jubako.svg" && -f "$data/mime/packages/jubako.xml" ]] \
  && ok "icons and file type installed" || fail "icons or MIME file missing"
XDG_DATA_HOME="$data" "$image" --install-desktop-entry >/dev/null && ok "install is idempotent" || fail "second install"
XDG_DATA_HOME="$data" "$image" --remove-desktop-entry
left="$(find "$data" -type f -name 'jubako*' 2>/dev/null)"
[[ -z "$left" ]] && ok "remove takes every file away" || fail "left behind: $left"
"$appdir/AppRun" --install-desktop-entry >/dev/null 2>&1 && fail "install from an extracted AppDir should refuse" \
  || ok "install from an extracted AppDir refuses kindly"

echo
if [[ $failures -gt 0 ]]; then
  echo "$failures check(s) failed." >&2
  exit 1
fi
echo "All AppImage checks passed. Size: $(du -h "$image" | cut -f1)"
