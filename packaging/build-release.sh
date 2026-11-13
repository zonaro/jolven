#!/usr/bin/env bash
# Build a version-frozen native package or a portable GTK4/Python AppImage.
# Run on Debian 13 (deb/appimage) or Fedora (rpm) in a disposable CI container.
set -Eeuo pipefail

format="${1:?Usage: packaging/build-release.sh deb|rpm|appimage}"
case "$format" in deb|rpm|appimage) ;; *) echo "Unknown format: $format" >&2; exit 64;; esac

cd "$(dirname "$0")/.."
: "${JOLVEN_VERSION:?JOLVEN_VERSION must be set by the release workflow}"
actual="$(python3 build-aux/get-version.py)"
[[ "$actual" == "$JOLVEN_VERSION" ]] || { echo "Version mismatch" >&2; exit 1; }
[[ "$(uname -m)" == x86_64 ]] || { echo "Only x86_64 is packaged for now" >&2; exit 1; }
export TZ=UTC

if [[ "$format" == rpm ]]; then
  dnf install -y --setopt=install_weak_deps=False \
    meson ninja-build gcc gcc-c++ pkgconf-pkg-config gtk4-devel libadwaita-devel \
    blueprint-compiler gettext glib2-devel desktop-file-utils appstream \
    python3 python3-gobject python3-pillow python3-requests python3-pyyaml \
    python3-attrs python3-jinja2 python3-cairo \
    ruby ruby-devel rubygems make rpm-build tar gzip
else
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends \
    meson ninja-build gcc g++ pkg-config libgtk-4-dev libadwaita-1-dev \
    blueprint-compiler gettext libglib2.0-dev desktop-file-utils appstream \
    python3 python3-gi python3-gi-cairo python3-pil python3-requests \
    python3-yaml python3-attr python3-jinja2 \
    ca-certificates curl xz-utils file
  if [[ "$format" == deb ]]; then
    apt-get install -y --no-install-recommends ruby ruby-dev make dpkg-dev build-essential
  else
    apt-get install -y --no-install-recommends libfuse2t64 xvfb xauth
  fi
fi

meson setup .release/build --prefix=/usr --buildtype=release -Dprofile=release \
  -Dsystem_libexecdir=/usr/libexec
meson compile -C .release/build
meson test -C .release/build --print-errorlogs

if [[ "$format" == appimage ]]; then
  stage="$PWD/AppDir"
else
  stage="$PWD/.release/stage"
fi
mkdir -p "$stage"
DESTDIR="$stage" meson install -C .release/build --no-rebuild

test -f "$stage/usr/share/jolven/jolven.gresource"
test -f "$stage/usr/bin/jolven"
test -f "$stage/usr/share/glib-2.0/schemas/io.github.zonaro.Jolven.gschema.xml"
test -f "$stage/usr/share/applications/io.github.zonaro.Jolven.desktop"
grep -q "BUILD_VERSION = \"$JOLVEN_VERSION\"" "$(find "$stage/usr" -path '*/cartridges/version.py' -print -quit)"
mkdir -p dist

if [[ "$format" == appimage ]]; then
  # This builder resolves Debian package dependencies into the AppDir, including
  # Python, PyGObject/GI typelibs, GTK4 and libadwaita; it is not a tarball rename.
  curl --fail --location --retry 3 \
    -o .release/appimage-builder.AppImage \
    https://github.com/AppImageCrafters/appimage-builder/releases/download/v1.1.0/appimage-builder-1.1.0-x86_64.AppImage
  chmod 0755 .release/appimage-builder.AppImage
  export APPIMAGE_EXTRACT_AND_RUN=1
  .release/appimage-builder.AppImage --recipe packaging/appimage-builder.yml --skip-script --skip-test
  artifact="dist/Jolven-${JOLVEN_VERSION}-x86_64.AppImage"
  test -s "$artifact"
  chmod 0755 "$artifact"
  # Extract without requiring FUSE; validate both the AppRun entry and schema.
  "$artifact" --appimage-extract >/dev/null
  test -x squashfs-root/AppRun
  test -f squashfs-root/usr/bin/jolven
  test -f squashfs-root/usr/share/glib-2.0/schemas/gschemas.compiled
  xvfb-run -a env APPIMAGE_EXTRACT_AND_RUN=1 "$artifact" --help >/dev/null
else
  gem install fpm --no-document --version 1.17.0
  common=(
    -s dir -t "$format" -n jolven -v "$JOLVEN_VERSION" --iteration 1
    --license GPL-3.0-or-later
    --vendor "Jolven contributors"
    --url https://github.com/zonaro/jolven
    --description "Gamepad-first gaming interface for Linux desktops"
    --category games
    --after-install packaging/post-install.sh
    --after-remove packaging/post-remove.sh
    -C "$stage"
  )
  if [[ "$format" == rpm ]]; then
    fpm "${common[@]}" -a x86_64 -p "dist/jolven-${JOLVEN_VERSION}-1.x86_64.rpm" \
      -d gtk4 -d libadwaita -d python3 -d python3-gobject \
      -d python3-pillow -d python3-requests -d python3-pyyaml \
      -d python3-attrs -d python3-jinja2 usr
    rpm -qp --queryformat '%{VERSION}' "dist/jolven-${JOLVEN_VERSION}-1.x86_64.rpm" |
      grep -Fx "$JOLVEN_VERSION"
  else
    fpm "${common[@]}" -a amd64 -p "dist/jolven_${JOLVEN_VERSION}_amd64.deb" \
      -d 'gir1.2-gtk-4.0 (>= 4.15)' -d 'gir1.2-adw-1 (>= 1.6)' \
      -d python3 -d python3-gi -d python3-pil -d python3-requests \
      -d python3-yaml -d python3-attr -d python3-jinja2 usr
    dpkg-deb --field "dist/jolven_${JOLVEN_VERSION}_amd64.deb" Version |
      grep -F "$JOLVEN_VERSION"
  fi
fi

find dist -maxdepth 1 -type f -print -exec ls -lh {} \;
