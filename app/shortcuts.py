"""Windows shortcuts with the tool's icons (a .cmd file itself cannot have an icon of its own).

    shortcuts.py folder           the shortcuts in the tool folder (called by windows\\setup.cmd)
    shortcuts.py sendto-add       the "Расшифровать" entry in the Explorer Send To menu
    shortcuts.py sendto-remove    removes it (also the entries of older versions)
    shortcuts.py sendto-status

Shortcuts hold absolute paths, so they are made on each computer and are not in git; after
moving the tool folder, run windows\\setup.cmd again. Files can be dragged onto the
"Расшифровать запись" shortcut like onto drop-files-here.cmd.
"""
import base64
import os
import subprocess
import sys

APP = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP)
WINDOWS = os.path.join(ROOT, "windows")
ICONS = os.path.join(APP, "icons")
# Shortcut name -> (script in windows\, icon, window style: 1 normal, 7 minimized).
FOLDER_SHORTCUTS = {
    "Расшифровать запись": ("drop-files-here.cmd", "transcribe.ico", 1),
    # Its console only shows technical messages; the window is what people use.
    "Расшифровка встречи на лету": ("live-transcribe.cmd", "live.ico", 7),
    "Установка и обновление": ("setup.cmd", "setup.ico", 1),
}
SENDTO_SHORTCUTS = {"Расшифровать": ("drop-files-here.cmd", "transcribe.ico", 1)}
# Send To entries made by older versions; removed by sendto-add and sendto-remove.
OLD_SENDTO = ["Расшифровать (текст)", "Расшифровать (текст и выжимка)"]

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


def folder() -> int:
    ok = all(create(ROOT, name, *spec) for name, spec in FOLDER_SHORTCUTS.items())
    if ok:
        print("Shortcuts in the tool folder: " + ", ".join(FOLDER_SHORTCUTS))
    return 0 if ok else 1


def send_to_dir() -> str:
    return os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "SendTo")


def remove_old() -> None:
    for name in OLD_SENDTO:
        path = os.path.join(send_to_dir(), name + ".lnk")
        if os.path.isfile(path):
            os.remove(path)
            print(f"Removed old entry from Send To: {name}")


def sendto_add() -> int:
    os.makedirs(send_to_dir(), exist_ok=True)
    remove_old()
    for name, spec in SENDTO_SHORTCUTS.items():
        if not create(send_to_dir(), name, *spec):
            return 1
        print(f"Added to Send To: {name}")
    return 0


def sendto_remove() -> int:
    remove_old()
    for name in SENDTO_SHORTCUTS:
        path = os.path.join(send_to_dir(), name + ".lnk")
        if os.path.isfile(path):
            os.remove(path)
            print(f"Removed from Send To: {name}")
    return 0


def sendto_status() -> int:
    present = [n for n in SENDTO_SHORTCUTS if os.path.isfile(os.path.join(send_to_dir(), n + ".lnk"))]
    print("In the Send To menu: " + (", ".join(present) if present else "no"))
    return 0


def main() -> int:
    actions = {"folder": folder, "sendto-add": sendto_add, "sendto-remove": sendto_remove,
               "sendto-status": sendto_status}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        print("Usage: shortcuts.py " + " | ".join(actions), file=sys.stderr)
        return 2
    return actions[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
