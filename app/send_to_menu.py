"""Adds the tool to the Explorer "Send To" menu, or removes it again.

Usage (via send-to-menu.cmd):  send-to-menu.cmd add | remove | status

Creates one shortcut, "Расшифровать", in the user's SendTo folder
(%APPDATA%\\Microsoft\\Windows\\SendTo) that points to drop-files-here.cmd in the tool folder.
Nothing else is changed; "remove" deletes exactly the tool's shortcuts (also those of older
versions). After moving the tool folder, run "add" again.
"""
import base64
import os
import subprocess
import sys

# This file is in app\; the scripts people start are one level up.
TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Shortcut name (as shown in the menu) -> script in the tool folder.
SHORTCUTS = {
    "Расшифровать": "drop-files-here.cmd",
}
# Shortcuts made by older versions; removed by "add" and "remove".
OLD_SHORTCUTS = ["Расшифровать (текст)", "Расшифровать (текст и выжимка)"]

# Creates one shortcut; the paths come in through environment variables, so no quoting of
# user paths inside the PowerShell code is needed.
CREATE_SHORTCUT_PS = """
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($env:SENDTO_LINK)
$link.TargetPath = $env:SENDTO_TARGET
$link.WorkingDirectory = $env:SENDTO_WORKDIR
$link.Description = $env:SENDTO_DESCRIPTION
$link.Save()
"""


def send_to_dir() -> str:
    return os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "SendTo")


def link_path(name: str) -> str:
    return os.path.join(send_to_dir(), name + ".lnk")


def remove_old() -> None:
    for name in OLD_SHORTCUTS:
        if os.path.isfile(link_path(name)):
            os.remove(link_path(name))
            print(f"Removed old entry from Send To: {name}")


def add() -> int:
    os.makedirs(send_to_dir(), exist_ok=True)
    remove_old()
    encoded = base64.b64encode(CREATE_SHORTCUT_PS.encode("utf-16-le")).decode("ascii")
    for number, (name, script) in enumerate(SHORTCUTS.items()):
        # WScript.Shell saves through the ANSI code page and fails on Cyrillic names, so the
        # shortcut is saved under an ASCII name and renamed here.
        temporary = os.path.join(send_to_dir(), f"transcribe-shortcut-{number}.lnk")
        env = dict(os.environ,
                   SENDTO_LINK=temporary,
                   SENDTO_TARGET=os.path.join(TOOL_DIR, script),
                   SENDTO_WORKDIR=TOOL_DIR,
                   SENDTO_DESCRIPTION="Meeting transcription: " + script)
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-EncodedCommand", encoded],
            env=env, capture_output=True, text=True)
        if result.returncode != 0 or not os.path.isfile(temporary):
            print(f"Could not create the shortcut {name}: {result.stderr.strip()}", file=sys.stderr)
            return 1
        os.replace(temporary, link_path(name))
        print(f"Added to Send To: {name}")
    return 0


def remove() -> int:
    remove_old()
    for name in SHORTCUTS:
        if os.path.isfile(link_path(name)):
            os.remove(link_path(name))
            print(f"Removed from Send To: {name}")
    return 0


def status() -> int:
    present = [name for name in SHORTCUTS if os.path.isfile(link_path(name))]
    print("In the Send To menu: " + (", ".join(present) if present else "no"))
    return 0


def main() -> int:
    actions = {"add": add, "remove": remove, "status": status}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        print("Usage: send-to-menu.cmd add | remove | status", file=sys.stderr)
        return 2
    return actions[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
