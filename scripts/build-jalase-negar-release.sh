#!/usr/bin/env bash
# Builds Jalase-Negar release artifacts into jalase-negar/dist/<version>/.
# Usage: scripts/build-jalase-negar-release.sh [android|ios|macos|all]
# Windows cannot be built on macOS: use .github/workflows/jalase-negar-windows.yml.
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$script_dir/../jalase-negar"
target="${1:-all}"
version="$(grep -E '^version:' pubspec.yaml | awk '{print $2}')"
out="dist/$version"
mkdir -p "$out"
export JALASE_KEY_PROPERTIES="${JALASE_KEY_PROPERTIES:-$HOME/.sedasanj-secrets/jalase-negar/key.properties}"

android() {
  [ -f "$JALASE_KEY_PROPERTIES" ] || { echo "Missing release signing file: $JALASE_KEY_PROPERTIES (set JALASE_KEY_PROPERTIES)." >&2; exit 1; }
  local -a build_args=(--target-platform android-arm64)
  if [ -n "${JALASE_PUSH_CONFIG:-}" ]; then
    [ -f "$JALASE_PUSH_CONFIG" ] || { echo "Firebase build config file is missing." >&2; exit 1; }
    build_args+=("--dart-define-from-file=$JALASE_PUSH_CONFIG")
  fi
  for store in direct bazaar myket; do
    flutter build apk --release --flavor "$store" --dart-define=STORE="$store" "${build_args[@]}"
    cp "build/app/outputs/flutter-apk/app-$store-release.apk" "$out/JalaseNegar-$store-v$version.apk"
  done
}

ios() {
  # Unsigned archive: SibApp Export / the store panel re-signs it. No Apple certificate is used.
  # `flutter build ipa --no-codesign` stops at "requires a Development Team", so Flutter only
  # prepares the project (pods + --dart-define) and xcodebuild makes the archive with signing off.
  flutter build ios --config-only --release --no-codesign --dart-define=STORE=sibapp
  rm -rf build/ios/archive
  xcodebuild -workspace ios/Runner.xcworkspace -scheme Runner -configuration Release -sdk iphoneos \
    -archivePath build/ios/archive/Runner.xcarchive \
    CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY="" DEVELOPMENT_TEAM="" archive
  rm -rf "$out/JalaseNegar-v$version.xcarchive"
  cp -R build/ios/archive/Runner.xcarchive "$out/JalaseNegar-v$version.xcarchive"
  rm -rf "$out/Payload" && mkdir -p "$out/Payload"
  cp -R build/ios/archive/Runner.xcarchive/Products/Applications/Runner.app "$out/Payload/"
  (cd "$out" && rm -f "JalaseNegar-unsigned-v$version.ipa" && zip -qry "JalaseNegar-unsigned-v$version.ipa" Payload && rm -rf Payload)
}

macos() {
  flutter build macos --release --dart-define=STORE=desktop
  # Xcode signs with the developer's own Apple Development cert + a device-bound provisioning profile,
  # which another Mac refuses to run. Drop the profile and ad-hoc re-sign with the real entitlements.
  local app=build/macos/Build/Products/Release/Jalase-Negar.app
  rm -f "$app/Contents/embedded.provisionprofile"
  codesign --force --deep --sign - --entitlements macos/Runner/Release.entitlements "$app"
  codesign --verify --deep --strict "$app"
  ditto -c -k --keepParent "$app" "$out/JalaseNegar-macos-v$version.zip"
  # Styled DMG (branded background, drag-to-Applications). Unsigned: first launch needs right-click > Open.
  "$script_dir/make-jalase-negar-dmg.sh" "$app" "$out/JalaseNegar-macos-v$version.dmg"
}

case "$target" in
  android) android ;; ios) ios ;; macos) macos ;;
  all) android; ios; macos ;;
  *) echo "Unknown target: $target" >&2; exit 2 ;;
esac
ls -la "$out"
