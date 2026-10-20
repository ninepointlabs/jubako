#!/usr/bin/env bash
# Build the Arch, .deb and .rpm packages in clean containers, into dist/.
#
#   scripts/build-packages.sh [--ref <git ref>] [--from-github] [--test]
#
# --ref          what to package (default HEAD); only committed files ship.
# --from-github  let makepkg fetch the tagged tarball from GitHub and check
#                it against the PKGBUILD's sha256sums, as an AUR build would.
# --test         install each package in a fresh container and smoke-test it.
#
# Needs Docker. Nothing is installed on this computer.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ref=HEAD
from_github=0
run_tests=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref) ref="$2"; shift 2 ;;
    --from-github) from_github=1; shift ;;
    --test) run_tests=1; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

version="$(git -C "$here" show "$ref:pyproject.toml" | sed -n 's/^version = "\(.*\)"/\1/p')"
out="$here/dist"
mkdir -p "$out"
tarball="jubako-$version.tar.gz"
git -C "$here" archive --prefix="jubako-$version/" -o "$out/$tarball" "$ref"
echo "Packaging Jubako $version from $ref"

owner="$(id -u):$(id -g)"

debian_depends=(
  "python3 (>= 3.11)"
  "python3-pyside6.qtcore (>= 6.6)" python3-pyside6.qtgui python3-pyside6.qtwidgets
  python3-pyside6.qtqml python3-pyside6.qtquick python3-pyside6.qtquickcontrols2
  python3-pyside6.qtprintsupport
  qml6-module-qtquick qml6-module-qtquick-controls qml6-module-qtquick-dialogs
  qml6-module-qtquick-layouts qml6-module-qtquick-templates qml6-module-qtquick-window
  qml6-module-qtqml-workerscript
)
depends_line="$(IFS=,; echo "${debian_depends[*]}" | sed 's/,/, /g')"

echo "== .deb (Debian 13)"
docker run --rm -v "$out:/out:z" -e V="$version" -e DEPENDS="$depends_line" -e OWNER="$owner" debian:13 bash -euc '
  cd /tmp && tar xzf "/out/jubako-$V.tar.gz" && cd "jubako-$V"
  root=/tmp/root
  packaging/stage.sh "$root"
  mv "$root/usr/share/licenses/jubako/LICENSE" "$root/usr/share/doc/jubako/copyright"
  rm -r "$root/usr/share/licenses"
  mkdir "$root/DEBIAN"
  cat >"$root/DEBIAN/control" <<EOF
Package: jubako
Version: $V-1
Architecture: all
Maintainer: Nine Point Labs <179739321+ninepointlabs@users.noreply.github.com>
Installed-Size: $(du -sk --exclude=DEBIAN "$root" | cut -f1)
Depends: $DEPENDS
Recommends: python3-openpyxl
Suggests: python3-psycopg, python3-pymysql
Section: misc
Priority: optional
Homepage: https://github.com/ninepointlabs/jubako
Description: simple desktop database, in the spirit of Microsoft Access
 Make a database, put a spreadsheet in it, look at your rows, print a tidy
 list. No SQL to learn, no server to set up. A Qt Quick window, a command
 line and an MCP server for agents, over one SQLite file per database.
EOF
  dpkg-deb --root-owner-group -Zxz --build "$root" "/out/jubako_$V-1_all.deb"
  chown "$OWNER" "/out/jubako_$V-1_all.deb"
'

echo "== .rpm (Fedora 44)"
docker run --rm -v "$out:/out:z" -e V="$version" -e OWNER="$owner" fedora:44 bash -euc '
  dnf -q -y install rpm-build >/dev/null
  mkdir -p ~/rpmbuild/SOURCES
  cp "/out/jubako-$V.tar.gz" ~/rpmbuild/SOURCES/
  tar xzf "/out/jubako-$V.tar.gz" -C /tmp "jubako-$V/packaging/rpm/jubako.spec"
  rpmbuild -bb --quiet --define "dist %{nil}" "/tmp/jubako-$V/packaging/rpm/jubako.spec"
  cp ~/rpmbuild/RPMS/noarch/jubako-*.rpm /out/
  chown "$OWNER" /out/jubako-*.rpm
'

echo "== Arch"
docker run --rm -v "$out:/out:z" -e V="$version" -e OWNER="$owner" -e FROM_GITHUB="$from_github" archlinux:latest bash -euc '
  pacman -Syu --noconfirm --needed base-devel python-build python-installer python-hatchling pyside6 qt6-declarative >/dev/null
  useradd -m builder
  build=/home/builder/build
  mkdir "$build"
  tar xzf "/out/jubako-$V.tar.gz" -O "jubako-$V/packaging/arch/PKGBUILD" >"$build/PKGBUILD"
  flags=()
  if [[ "$FROM_GITHUB" != 1 ]]; then
    cp "/out/jubako-$V.tar.gz" "$build/"
    flags+=(--skipchecksums)
  fi
  chown -R builder "$build"
  su builder -c "cd $build && makepkg --noconfirm ${flags[*]:-}"
  cp "$build"/jubako-*.pkg.tar.zst /out/
  chown "$OWNER" /out/jubako-*.pkg.tar.zst
'

ls -l "$out"

[[ $run_tests == 1 ]] || exit 0

# Same checks everywhere: the command line makes and fills a database, the MCP
# server answers, and the window starts (offscreen) with every QML module found.
smoke='
  set -eu
  cd /root
  jubako --help >/dev/null
  jubako new Demo /root/demo >/dev/null
  jubako import /root/demo.jubadb /root/pets.csv >/dev/null
  jubako tables /root/demo.jubadb | grep -q "pets"
  echo "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-06-18\",\"capabilities\":{},\"clientInfo\":{\"name\":\"smoke\",\"version\":\"0\"}}}" | jubako-mcp | grep -q "\"name\": \"jubako\""
  set +e
  QT_QPA_PLATFORM=offscreen timeout 8 jubako-app >/tmp/app.log 2>&1
  rc=$?
  set -e
  if [ $rc -ne 124 ] || grep -Eiq "error|not installed|cannot|failed" /tmp/app.log; then
    echo "window failed to start (exit $rc):"; cat /tmp/app.log; exit 1
  fi
  echo "ok: cli, mcp, window"
'
pets="$here/data/examples/pets.csv:/root/pets.csv:ro,z"

for image in debian:13 ubuntu:26.04; do
  echo "== test .deb on $image"
  docker run --rm -v "$out:/out:ro,z" -v "$pets" "$image" bash -c "
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq >/dev/null && apt-get install -y -qq /out/jubako_${version}-1_all.deb >/dev/null && $smoke"
done

echo "== test .rpm on fedora:44"
docker run --rm -v "$out:/out:ro,z" -v "$pets" fedora:44 bash -c "
  dnf -q -y install /out/jubako-${version}-1.noarch.rpm >/dev/null && $smoke"

# The same .rpm, as built on Fedora, on openSUSE. It is unsigned, as it is for anyone
# who downloads it from a release.
echo "== test .rpm on opensuse/tumbleweed"
docker run --rm -v "$out:/out:ro,z" -v "$pets" opensuse/tumbleweed bash -c "
  zypper -q -n in --allow-unsigned-rpm /out/jubako-${version}-1.noarch.rpm >/dev/null && $smoke"

echo "== test Arch package on archlinux:latest"
docker run --rm -v "$out:/out:ro,z" -v "$pets" archlinux:latest bash -c "
  pacman -Syu --noconfirm >/dev/null && pacman -U --noconfirm /out/jubako-${version}-1-any.pkg.tar.zst >/dev/null && $smoke"
