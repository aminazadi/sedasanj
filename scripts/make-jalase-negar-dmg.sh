#!/usr/bin/env bash
# Builds the styled Jalase-Negar DMG: branded background, big icons, app + Applications link,
# volume icon. Usage: scripts/make-jalase-negar-dmg.sh <path/to/Jalase-Negar.app> <output.dmg>
# Needs a logged-in desktop session: Finder lays the window out through AppleScript, and macOS may
# ask once to let Terminal/Claude control Finder.
set -euo pipefail
app="${1:?path to Jalase-Negar.app}"
out="${2:?output .dmg path}"
root="$(cd "$(dirname "$0")/.." && pwd)"
art="$root/jalase-negar/macos/dmg"
vol="Jalase-Negar"
work="$(mktemp -d)"
rw="$work/rw.dmg"
trap 'hdiutil detach "/Volumes/$vol" -quiet >/dev/null 2>&1 || true; rm -rf "$work"' EXIT
hdiutil detach "/Volumes/$vol" -quiet >/dev/null 2>&1 || true

# Retina-aware background (1x + 2x in one multi-resolution TIFF)
tiffutil -cathidpicheck "$art/background.png" "$art/background@2x.png" -out "$work/background.tiff" >/dev/null

stage="$work/stage"
mkdir -p "$stage/.background"
ditto "$app" "$stage/Jalase-Negar.app"
ln -s /Applications "$stage/Applications"
cp "$work/background.tiff" "$stage/.background/background.tiff"

# Volume icon from the app's own icon set
icons="$root/jalase-negar/macos/Runner/Assets.xcassets/AppIcon.appiconset"
set_dir="$work/Jalase.iconset"; mkdir -p "$set_dir"
for s in 16 32 128 256 512; do
  cp "$icons/app_icon_$s.png" "$set_dir/icon_${s}x${s}.png"
  d=$((s * 2)); [ -f "$icons/app_icon_$d.png" ] && cp "$icons/app_icon_$d.png" "$set_dir/icon_${s}x${s}@2x.png"
done
iconutil -c icns "$set_dir" -o "$stage/.VolumeIcon.icns"

hdiutil create -srcfolder "$stage" -volname "$vol" -fs HFS+ -format UDRW -ov "$rw" >/dev/null
hdiutil attach "$rw" -noautoopen -nobrowse -mountpoint "/Volumes/$vol" >/dev/null
SetFile -a C "/Volumes/$vol" 2>/dev/null || true
SetFile -a V "/Volumes/$vol/.background" "/Volumes/$vol/.VolumeIcon.icns" 2>/dev/null || true

osascript <<OSA
tell application "Finder"
  tell disk "$vol"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {200, 120, 860, 560}
    set opts to the icon view options of container window
    set arrangement of opts to not arranged
    set icon size of opts to 128
    set text size of opts to 13
    set background picture of opts to file ".background:background.tiff"
    set position of item "Jalase-Negar.app" of container window to {180, 215}
    set position of item "Applications" of container window to {480, 215}
    close
    open
    update without registering applications
    delay 2
  end tell
end tell
OSA
sync
hdiutil detach "/Volumes/$vol" -quiet
rm -f "$out"
hdiutil convert "$rw" -format UDZO -imagekey zlib-level=9 -o "$out" >/dev/null
echo "DMG written: $out"
