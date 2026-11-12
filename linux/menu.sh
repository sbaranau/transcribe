#!/usr/bin/env bash
# Optional: the tool's entries with their icons in the applications menu, or removes them.
#   linux/menu.sh add | remove | status
# "Расшифровать запись" also appears under Open With for audio and video files in the file manager.
# The entries hold absolute paths; after moving the tool folder, run linux/menu.sh add again.
set -euo pipefail
LINUX="$(dirname "$(readlink -f "$0")")"
ROOT="$(cd "$LINUX/.." && pwd)"
ICONS="$ROOT/app/icons"
DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
# Listed one by one: file managers do not reliably accept audio/* in MimeType.
MEDIA_TYPES="audio/mpeg;audio/mp4;audio/x-m4a;audio/wav;audio/x-wav;audio/ogg;audio/flac;audio/webm;audio/aac;\
video/mp4;video/x-matroska;video/webm;video/quicktime;video/x-msvideo;video/mpeg;"
# file name | name | script | icon | terminal | file types
ENTRIES=(
    "transcribe-recording|Расшифровать запись|drop-files-here.sh %F|transcribe|true|$MEDIA_TYPES"
    "transcribe-live|Расшифровка встречи на лету|live-transcribe.sh|live|false|"
    "transcribe-setup|Расшифровка: установка и обновление|setup.sh|setup|true|"
)

quote() {  # a path as a quoted argument of the Exec key
    printf '"%s"' "$(printf '%s' "$1" | sed -e 's/\\/\\\\\\\\/g' -e 's/"/\\\\"/g' -e 's/`/\\\\`/g' -e 's/\$/\\\\$/g')"
}

add() {
    mkdir -p "$DIR"
    for entry in "${ENTRIES[@]}"; do
        IFS='|' read -r file name command icon terminal types <<<"$entry"
        script="${command%% *}"
        args="${command#"$script"}"
        {
            echo "[Desktop Entry]"
            echo "Type=Application"
            echo "Name=$name"
            echo "Comment=Meeting transcription"
            echo "Exec=$(quote "$LINUX/$script")$args"
            echo "Icon=$ICONS/$icon.png"
            echo "Terminal=$terminal"
            echo "Categories=AudioVideo;Utility;"
            [ -n "$types" ] && echo "MimeType=$types"
        } >"$DIR/$file.desktop"
        echo "Added to the menu: $name"
    done
    command -v update-desktop-database >/dev/null && update-desktop-database "$DIR" 2>/dev/null || true
}

remove() {
    for entry in "${ENTRIES[@]}"; do
        IFS='|' read -r file name _ <<<"$entry"
        if [ -f "$DIR/$file.desktop" ]; then
            rm -f "$DIR/$file.desktop"
            echo "Removed from the menu: $name"
        fi
    done
    command -v update-desktop-database >/dev/null && update-desktop-database "$DIR" 2>/dev/null || true
}

status() {
    present=()
    for entry in "${ENTRIES[@]}"; do
        IFS='|' read -r file name _ <<<"$entry"
        [ -f "$DIR/$file.desktop" ] && present+=("$name")
    done
    if [ ${#present[@]} -eq 0 ]; then
        echo "In the applications menu: no"
    else
        echo "In the applications menu: $(IFS=,; echo "${present[*]}")"
    fi
}

case "${1:-}" in
    add) add ;;
    remove) remove ;;
    status) status ;;
    *) echo "Usage: linux/menu.sh add | remove | status" >&2; exit 2 ;;
esac
