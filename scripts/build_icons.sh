#!/usr/bin/env bash
# Rebuild the app icons from the SVGs (the Ink skin's logo): packaging/icon.icns (macOS grid, icon.svg) and
# packaging/icon.ico (full-bleed icon-full.svg; 16-32 px from the plain d20 of icon-small.svg).
# Needs Inkscape and macOS's iconutil; Pillow comes from the backend's environment.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

render() { inkscape "$1" -w "$2" -h "$2" -o "$3" 2>/dev/null; }

mkdir "$TMP/icon.iconset"
for size in 16 32 128 256 512; do
  render "$ROOT/packaging/icon.svg" "$size" "$TMP/icon.iconset/icon_${size}x${size}.png"
  render "$ROOT/packaging/icon.svg" "$((size * 2))" "$TMP/icon.iconset/icon_${size}x${size}@2x.png"
done
iconutil -c icns "$TMP/icon.iconset" -o "$ROOT/packaging/icon.icns"

for size in 16 24 32; do render "$ROOT/packaging/icon-small.svg" "$size" "$TMP/win-$size.png"; done
for size in 48 64 128 256; do render "$ROOT/packaging/icon-full.svg" "$size" "$TMP/win-$size.png"; done
cd "$ROOT/backend"
uv run python - "$TMP" "$ROOT/packaging/icon.ico" <<'EOF'
import sys
from PIL import Image

tmp, out = sys.argv[1:]
sizes = [16, 24, 32, 48, 64, 128, 256]
images = [Image.open(f"{tmp}/win-{size}.png").convert("RGBA") for size in sizes]
images[-1].save(out, format="ICO", sizes=[(size, size) for size in sizes], append_images=images[:-1])
EOF
echo "packaging/icon.icns, packaging/icon.ico"
