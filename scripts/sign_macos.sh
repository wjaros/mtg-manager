#!/usr/bin/env bash
# Sign an already built "MTG Deck Manager.app" with a Developer ID, notarize it and produce a DMG
# that opens on any Mac without Gatekeeper warnings. Needs Xcode command line tools and:
#
#   SIGN_IDENTITY   e.g. "Developer ID Application: Jane Doe (TEAMID1234)"  (see: security find-identity -v -p codesigning)
#   NOTARY_PROFILE  keychain profile for notarytool, created once with:
#                   xcrun notarytool store-credentials NAME --apple-id ME@EXAMPLE.COM --team-id TEAMID1234
#                   (leave empty to sign only, without notarization)
#
# Usage: scripts/sign_macos.sh "path/to/MTG Deck Manager.app" [output.dmg]
set -euo pipefail
SRC="${1:?path to MTG Deck Manager.app}"
OUT="${2:-$(pwd)/MTG-Deck-Manager-signed.dmg}"
IDENTITY="${SIGN_IDENTITY:?set SIGN_IDENTITY (Developer ID Application: ...)}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENTITLEMENTS="$ROOT/packaging/entitlements.plist"

# Work outside iCloud-synced folders: their extended attributes break code signatures.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
APP="$STAGE/MTG Deck Manager.app"
ditto --norsrc --noextattr "$SRC" "$APP"

echo "==> Signing nested code (inside-out) with hardened runtime"
# Libraries and extension modules: hardened runtime + timestamp, no entitlements.
while IFS= read -r -d '' file; do
  if [ "$file" != "$APP/Contents/MacOS/mtgdm" ] && file -b "$file" | grep -q "Mach-O"; then
    codesign --force --timestamp --options runtime --sign "$IDENTITY" "$file"
  fi
done < <(find "$APP/Contents" -type f -print0)
# Main executable and bundle: the only place that needs the entitlements.
codesign --force --timestamp --options runtime --entitlements "$ENTITLEMENTS" --sign "$IDENTITY" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

notarize() {  # $1 = file to submit (zip, dmg); prints the notary log on failure
  local out id
  out="$(xcrun notarytool submit "$1" --keychain-profile "$NOTARY_PROFILE" --wait --output-format plist)" || true
  id="$(/usr/libexec/PlistBuddy -c "Print :id" /dev/stdin <<<"$out" 2>/dev/null || true)"
  if ! /usr/libexec/PlistBuddy -c "Print :status" /dev/stdin <<<"$out" 2>/dev/null | grep -q "^Accepted$"; then
    echo "Notarization failed for $1:" >&2
    echo "$out" >&2
    [ -n "$id" ] && xcrun notarytool log "$id" --keychain-profile "$NOTARY_PROFILE" >&2
    exit 1
  fi
  echo "Accepted (submission $id)"
}

if [ -n "${NOTARY_PROFILE:-}" ]; then
  # Staple the app itself so it passes Gatekeeper offline after being copied out of the DMG.
  echo "==> Notarizing the app (a few minutes)"
  ditto -c -k --keepParent "$APP" "$STAGE/app.zip"
  notarize "$STAGE/app.zip"
  xcrun stapler staple "$APP"
  xcrun stapler validate "$APP"
fi

echo "==> Disk image"
mkdir "$STAGE/dmg"
ditto "$APP" "$STAGE/dmg/MTG Deck Manager.app"
ln -s /Applications "$STAGE/dmg/Applications"
hdiutil create -quiet -volname "MTG Deck Manager" -srcfolder "$STAGE/dmg" -ov -format UDZO "$STAGE/out.dmg"
codesign --force --timestamp --sign "$IDENTITY" "$STAGE/out.dmg"

if [ -n "${NOTARY_PROFILE:-}" ]; then
  echo "==> Notarizing the disk image"
  notarize "$STAGE/out.dmg"
  xcrun stapler staple "$STAGE/out.dmg"
  spctl --assess --type open --context context:primary-signature -vv "$STAGE/out.dmg"
  spctl --assess --type execute -vv "$APP"
else
  echo "NOTARY_PROFILE not set: signed but NOT notarized (other Macs will still block it)."
fi

cp "$STAGE/out.dmg" "$OUT"
echo
echo "DMG: $OUT"
