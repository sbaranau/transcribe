#!/usr/bin/env bash
# Builds the single-file macOS download published on GitHub Releases.
set -euo pipefail

MACOS="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$MACOS/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
BUILD="$ROOT/build/macos-release"
DIST="$ROOT/dist"
APP="$BUILD/Live Transcription.app"
RESOURCES="$APP/Contents/Resources"
DMG="$DIST/Live-Transcription-macOS-Apple-Silicon-v$VERSION.dmg"

case "$BUILD" in "$ROOT/build/"*) ;; *) echo "Unsafe build path: $BUILD" >&2; exit 1;; esac
rm -rf "$BUILD"
mkdir -p "$BUILD" "$DIST"

/usr/bin/ditto "$MACOS/Live Transcription.app" "$APP"
rm -rf "$APP/Contents/_CodeSignature"
cp "$MACOS/release/launcher" "$APP/Contents/MacOS/live-transcription"
chmod +x "$APP/Contents/MacOS/live-transcription"
rm -f "$RESOURCES/project-root" "$RESOURCES/project-root.txt"
mkdir -p "$RESOURCES/app"
rsync -a --delete \
    --exclude '__pycache__' --exclude '*.local.ini' --exclude 'models' \
    --exclude 'python' --exclude 'venv' "$ROOT/app/" "$RESOURCES/app/"
cp "$ROOT/VERSION" "$ROOT/LICENSE" "$RESOURCES/"

command -v uv >/dev/null 2>&1 || {
    echo "uv is required: https://docs.astral.sh/uv/" >&2
    exit 1
}
uv python install 3.12 --install-dir "$RESOURCES/python" --no-bin
PY="$(find "$RESOURCES/python" -type f -path '*/bin/python3.12' -perm -111 | head -n 1)"
[ -n "$PY" ] || { echo "Bundled Python was not created." >&2; exit 1; }
uv venv --relocatable "$RESOURCES/venv" --python "$PY"
VENV_PY="$RESOURCES/venv/bin/python"
uv pip install --python "$VENV_PY" --only-binary ':all:' -r "$ROOT/app/requirements.txt"
"$VENV_PY" -c 'import tkinter, faster_whisper, sherpa_onnx, soundcard, onnxruntime, tokenizers'
# uv keeps convenience links to the build path. Absolute links are not allowed in a signed app
# bundle and would also break after the user drags it to Applications.
find "$RESOURCES/python" -maxdepth 1 -type l -delete
PY_DISTRIBUTION="$(basename "$(dirname "$(dirname "$PY")")")"
rm "$RESOURCES/venv/bin/python"
ln -s "../../python/$PY_DISTRIBUTION/bin/python3.12" "$RESOURCES/venv/bin/python"

/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Delete :TranscribeProjectRoot" "$APP/Contents/Info.plist" 2>/dev/null || true

SIGN_IDENTITY="${MACOS_SIGN_IDENTITY:--}"
if [ "$SIGN_IDENTITY" = "-" ]; then
    /usr/bin/codesign --force --deep --sign - "$APP"
else
    /usr/bin/codesign --force --deep --options runtime --timestamp --sign "$SIGN_IDENTITY" "$APP"
fi
/usr/bin/codesign --verify --deep --strict "$APP"

STAGE="$BUILD/dmg"
mkdir -p "$STAGE"
/usr/bin/ditto "$APP" "$STAGE/Live Transcription.app"
ln -s /Applications "$STAGE/Applications"
/usr/bin/ditto "$MACOS/release/First Launch - Первый запуск.html" \
    "$STAGE/First Launch - Первый запуск.html"
rm -f "$DMG"
/usr/bin/hdiutil create -volname "Live Transcription" -srcfolder "$STAGE" -ov -format UDZO "$DMG"

if [ -n "${APPLE_NOTARY_PROFILE:-}" ]; then
    /usr/bin/xcrun notarytool submit "$DMG" --keychain-profile "$APPLE_NOTARY_PROFILE" --wait
    /usr/bin/xcrun stapler staple "$DMG"
fi

echo "$DMG"
