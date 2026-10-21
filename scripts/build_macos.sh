#!/usr/bin/env bash
# Build "MTG Deck Manager.app" (and a .dmg) for the current Mac architecture into dist/.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/dist/MTG Deck Manager.app"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/backend/mtgdm/__init__.py")"
ARCH="$(uname -m)"

echo "==> Frontend"
(cd "$ROOT/frontend" && npm ci --no-audit --no-fund && npm run build)

echo "==> Minimal OpenCV (cached in build/opencv-slim)"
(cd "$ROOT/backend" && uv sync)
CV2_DIR="$(cd "$ROOT/backend" && uv run python ../scripts/build_opencv.py)"

echo "==> Third-party licenses (build/licenses, bundled)"
(cd "$ROOT/backend" && uv run python ../scripts/collect_licenses.py "$CV2_DIR")

echo "==> Backend bundle (PyInstaller)"
# The minimal OpenCV shadows the PyPI wheel (~120 MB of video and image codecs the app never uses).
(cd "$ROOT/backend" && PYTHONPATH="$CV2_DIR" uv run pyinstaller --noconfirm --clean \
  --distpath "$ROOT/dist" --workpath "$ROOT/build/pyinstaller" "$ROOT/packaging/mtgdm.spec")
rm -rf "$ROOT/dist/mtgdm"  # intermediate onedir build; the .app contains everything

echo "==> Ad-hoc code signature (local use; distribution needs a Developer ID + notarization)"
# Sign and package outside the repo: iCloud-synced folders (~/Documents) re-add extended
# attributes, which strict signature verification rejects.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
ditto --norsrc --noextattr "$APP" "$STAGE/MTG Deck Manager.app"
codesign --force --deep --sign - "$STAGE/MTG Deck Manager.app"
codesign --verify --deep --strict "$STAGE/MTG Deck Manager.app"

echo "==> Disk image"
DMG_NAME="MTG-Deck-Manager-$VERSION-$ARCH.dmg"
# Drag-to-install layout: the app next to a link to /Applications.
mkdir "$STAGE/dmg"
ditto "$STAGE/MTG Deck Manager.app" "$STAGE/dmg/MTG Deck Manager.app"
ln -s /Applications "$STAGE/dmg/Applications"
hdiutil create -quiet -volname "MTG Deck Manager" -srcfolder "$STAGE/dmg" -ov -format UDZO "$STAGE/$DMG_NAME"

rm -rf "$APP"
ditto "$STAGE/MTG Deck Manager.app" "$APP"
cp "$STAGE/$DMG_NAME" "$ROOT/dist/$DMG_NAME"

echo
echo "App: $APP"
echo "DMG: $ROOT/dist/$DMG_NAME"
