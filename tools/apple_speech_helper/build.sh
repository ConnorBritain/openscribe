#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST="$ROOT/dist"
APP="$DIST/AppleSpeechHelper.app"
EXE_NAME="AppleSpeechHelper"

rm -rf "$DIST"
mkdir -p "$APP/Contents/MacOS"
mkdir -p "$APP/Contents/Resources"

echo "[build] compiling Swift..."
xcrun swiftc \
  "$ROOT/AppleSpeechHelper.swift" \
  -parse-as-library \
  -O \
  -framework AppKit \
  -framework Speech \
  -framework AVFoundation \
  -o "$APP/Contents/MacOS/$EXE_NAME"

cp "$ROOT/Info.plist" "$APP/Contents/Info.plist"

echo "[build] codesigning (ad-hoc, no timestamp)..."
codesign --force --sign - --deep --timestamp=none "$APP" >/dev/null

echo "[build] built: $APP"

