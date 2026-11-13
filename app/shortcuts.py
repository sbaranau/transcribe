"""Shortcuts with the tool's icons, named in the interface language (ui_text.py).

Windows (a .cmd file itself cannot have an icon of its own):
    shortcuts.py folder           the shortcuts in the tool folder (called by windows\\setup.cmd)
    shortcuts.py sendto-add       the "Transcribe" entry in the Explorer Send To menu
    shortcuts.py sendto-remove    removes it (also the entries of older versions)
    shortcuts.py sendto-status
Linux (called by linux/menu.sh):
    shortcuts.py menu-add         entries in the applications menu, the first also under Open With
    shortcuts.py menu-remove
    shortcuts.py menu-status

Shortcuts and entries hold absolute paths, so they are made on each computer and are not in
git; after moving the tool folder, run the setup again. Files can be dragged onto the
"Transcribe a recording" shortcut like onto drop-files-here.cmd. When the interface language
changes, the existing ones are renamed (rename_existing); the ones of other languages are
removed, so there is never a second set.
"""
import base64
import os
import subprocess
import sys

import ui_text

APP = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP)
WINDOWS = os.path.join(ROOT, "windows")
LINUX = os.path.join(ROOT, "linux")
ICONS = os.path.join(APP, "icons")
# Name key -> (script in windows\, icon, window style: 1 normal, 7 minimized).
FOLDER_SHORTCUTS = {
    "link.transcribe": ("drop-files-here.cmd", "transcribe.ico", 1),
    # Its console only shows technical messages; the window is what people use.
    "link.live": ("live-transcribe.cmd", "live.ico", 7),
    "link.setup": ("setup.cmd", "setup.ico", 1),
}
SENDTO_SHORTCUTS = {"link.sendto": ("drop-files-here.cmd", "transcribe.ico", 1)}
# Send To entries made by older versions; removed by sendto-add and sendto-remove.
OLD_SENDTO = ["Расшифровать (текст)", "Расшифровать (текст и выжимка)"]
# Linux: file name -> (name key, command in linux/, icon, in a terminal, file types).
MEDIA_TYPES = ("audio/mpeg;audio/mp4;audio/x-m4a;audio/wav;audio/x-wav;audio/ogg;audio/flac;audio/webm;"
               "audio/aac;video/mp4;video/x-matroska;video/webm;video/quicktime;video/x-msvideo;video/mpeg;")
MENU_ENTRIES = {
    "transcribe-recording": ("link.transcribe", "drop-files-here.sh", "%F", "transcribe", True, MEDIA_TYPES),
    "transcribe-live": ("link.live", "live-transcribe.sh", "", "live", False, ""),
    "transcribe-setup": ("link.setup_menu", "setup.sh", "", "setup", True, ""),
}

# Creates one shortcut; the paths come in through environment variables, so no quoting of user
# paths inside the PowerShell code is needed.
CREATE_SHORTCUT_PS = """
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($env:LINK_PATH)
$link.TargetPath = $env:LINK_TARGET
$link.WorkingDirectory = $env:LINK_WORKDIR
$link.IconLocation = $env:LINK_ICON + ",0"
$link.WindowStyle = [int]$env:LINK_STYLE
$link.Description = $env:LINK_DESCRIPTION
$link.Save()
"""


def all_names(key: str) -> list[str]:
    """The name of a shortcut in every interface language (to find the ones made before)."""
    return [ui_text.text_in(code, key) for code in ui_text.LANGUAGES]


# --- Windows ---------------------------------------------------------------------------------

def create(folder: str, name: str, script: str, icon: str, style: int) -> bool:
    # WScript.Shell saves through the ANSI code page and fails on Cyrillic names, so the
    # shortcut is saved under an ASCII name and renamed here.
    temporary = os.path.join(folder, "transcribe-shortcut.tmp.lnk")
    target = os.path.join(folder, name + ".lnk")
    env = dict(os.environ, LINK_PATH=temporary, LINK_TARGET=os.path.join(WINDOWS, script),
               LINK_WORKDIR=WINDOWS, LINK_ICON=os.path.join(ICONS, icon), LINK_STYLE=str(style),
               LINK_DESCRIPTION="Meeting transcription: " + name)
    encoded = base64.b64encode(CREATE_SHORTCUT_PS.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-EncodedCommand", encoded], env=env, capture_output=True, text=True)
    if result.returncode != 0 or not os.path.isfile(temporary):
        print(f"Could not create the shortcut {name}: {result.stderr.strip()}", file=sys.stderr)
        return False
    os.replace(temporary, target)
    return True


def remove_links(folder: str, names: list[str]) -> list[str]:
    removed = []
    for name in names:
        path = os.path.join(folder, name + ".lnk")
        if os.path.isfile(path):
            os.remove(path)
            removed.append(name)
    return removed


def folder() -> int:
    for key in FOLDER_SHORTCUTS:
        remove_links(ROOT, all_names(key))
    ok = all(create(ROOT, ui_text.t(key), *spec) for key, spec in FOLDER_SHORTCUTS.items())
    if ok:
        print("Shortcuts in the tool folder: " + ", ".join(ui_text.t(key) for key in FOLDER_SHORTCUTS))
    return 0 if ok else 1


def send_to_dir() -> str:
    return os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "SendTo")


def sendto_add() -> int:
    os.makedirs(send_to_dir(), exist_ok=True)
    for name in remove_links(send_to_dir(), OLD_SENDTO):
        print(f"Removed old entry from Send To: {name}")
    for key, spec in SENDTO_SHORTCUTS.items():
        remove_links(send_to_dir(), all_names(key))
        if not create(send_to_dir(), ui_text.t(key), *spec):
            return 1
        print(f"Added to Send To: {ui_text.t(key)}")
    return 0


def sendto_present() -> list[str]:
    return [name for key in SENDTO_SHORTCUTS for name in all_names(key)
            if os.path.isfile(os.path.join(send_to_dir(), name + ".lnk"))]


def sendto_remove() -> int:
    for key in SENDTO_SHORTCUTS:
        for name in remove_links(send_to_dir(), OLD_SENDTO + all_names(key)):
            print(f"Removed from Send To: {name}")
    return 0


def sendto_status() -> int:
    present = sendto_present()
    print("In the Send To menu: " + (", ".join(present) if present else "no"))
    return 0


# --- Linux -----------------------------------------------------------------------------------

def menu_dir() -> str:
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(data, "applications")


def exec_argument(path: str) -> str:
    """A path as a quoted argument of the Exec key (Desktop Entry spec: \\ " ` $ escaped inside
    the quotes, then backslashes escaped again as for any string value; % doubled)."""
    quoted = "".join("\\" + c if c in '\\"`$' else c for c in path).replace("%", "%%")
    return '"' + quoted.replace("\\", "\\\\") + '"'


def menu_add() -> int:
    os.makedirs(menu_dir(), exist_ok=True)
    for file, (key, script, field, icon, terminal, types) in MENU_ENTRIES.items():
        lines = ["[Desktop Entry]", "Type=Application", f"Name={ui_text.t(key)}",
                 "Comment=Meeting transcription",
                 f"Exec={exec_argument(os.path.join(LINUX, script))}" + (f" {field}" if field else ""),
                 f"Icon={os.path.join(ICONS, icon + '.png')}", f"Terminal={'true' if terminal else 'false'}",
                 "Categories=AudioVideo;Utility;"] + ([f"MimeType={types}"] if types else [])
        with open(os.path.join(menu_dir(), file + ".desktop"), "w", encoding="utf-8") as out:
            out.write("\n".join(lines) + "\n")
        print(f"Added to the menu: {ui_text.t(key)}")
    update_menu_database()
    return 0


def menu_present() -> list[str]:
    return [file for file in MENU_ENTRIES if os.path.isfile(os.path.join(menu_dir(), file + ".desktop"))]


def menu_remove() -> int:
    for file in menu_present():
        os.remove(os.path.join(menu_dir(), file + ".desktop"))
        print(f"Removed from the menu: {ui_text.t(MENU_ENTRIES[file][0])}")
    update_menu_database()
    return 0


def menu_status() -> int:
    present = [ui_text.t(MENU_ENTRIES[file][0]) for file in menu_present()]
    print("In the applications menu: " + (", ".join(present) if present else "no"))
    return 0


def update_menu_database() -> None:
    try:  # lets file managers see the Open With entry at once; optional
        subprocess.run(["update-desktop-database", menu_dir()], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass


# --- both ------------------------------------------------------------------------------------

def rename_existing() -> None:
    """After a change of the interface language: makes the existing shortcuts and entries again
    under the new names. Ones that were never made are not added."""
    if os.name == "nt":
        if any(os.path.isfile(os.path.join(ROOT, name + ".lnk"))
               for key in FOLDER_SHORTCUTS for name in all_names(key)):
            folder()
        if sendto_present():
            sendto_add()
    elif menu_present():
        menu_add()


def main() -> int:
    actions = {"folder": folder, "sendto-add": sendto_add, "sendto-remove": sendto_remove,
               "sendto-status": sendto_status, "menu-add": menu_add, "menu-remove": menu_remove,
               "menu-status": menu_status}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        print("Usage: shortcuts.py " + " | ".join(actions), file=sys.stderr)
        return 2
    return actions[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
