"""Installing an AI tool for the check and the summary: the official steps for Windows and macOS,
shown in the window (live_gui.show_ai_install) and, on request, run in a visible PowerShell or
Terminal window, where the person sees every command and answers its questions (login).

Only Claude Code and the Codex CLI are offered: both install for the current user without
administrator rights and log in with the person's own account, so no API key is asked for. The
other tools ai_engines finds (Gemini CLI, Copilot CLI, Qwen Code, local servers) still work when
installed some other way.
"""
import os
import subprocess
import sys

# Each guide: title key, then the steps as (text key, command). The commands run in this order;
# a later one must not rely on the PATH that an earlier one changed, since the running shell does
# not see that change (hence the full paths).
WINDOWS = [
    ("install.claude_title", [
        ("install.git_win", "winget install --id Git.Git -e --source winget"),
        ("install.claude_win", "irm https://claude.ai/install.ps1 | iex"),
        ("install.claude_login", '& "$env:USERPROFILE\\.local\\bin\\claude.exe"'),
    ]),
    ("install.codex_title", [
        ("install.node_win", "winget install --id OpenJS.NodeJS.LTS -e --source winget"),
        ("install.codex_win", '& "$env:ProgramFiles\\nodejs\\npm.cmd" install -g @openai/codex'),
        ("install.codex_login", '& "$env:APPDATA\\npm\\codex.cmd" login'),
    ]),
]

MACOS = [
    ("install.claude_title", [
        ("install.claude_mac", "curl -fsSL https://claude.ai/install.sh | bash"),
        ("install.path_mac", "grep -q '.local/bin' ~/.zprofile 2>/dev/null || "
                             "echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> ~/.zprofile"),
        ("install.claude_login", "~/.local/bin/claude"),
    ]),
    ("install.codex_title", [
        ("install.codex_mac", "curl -fsSL https://chatgpt.com/codex/install.sh | sh"),
        ("install.path_mac", "grep -q '.local/bin' ~/.zprofile 2>/dev/null || "
                             "echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> ~/.zprofile"),
        ("install.codex_login", "~/.local/bin/codex login"),
    ]),
]

GUIDES = WINDOWS if os.name == "nt" else MACOS if sys.platform == "darwin" else []
SHELL = "PowerShell" if os.name == "nt" else "Terminal"


def run_in_shell(commands: list[str]) -> None:
    """Opens a new PowerShell (Windows) or Terminal (macOS) window that runs the commands one
    after another and stays open, so the output and the login questions can be read."""
    if os.name == "nt":
        import base64
        # Each command is shown before it runs; a failed step (Git already installed) does not
        # stop the next one. Encoded, so its quotes need no escaping on the command line.
        script = "; ".join(f"Write-Host {quote_ps('> ' + command)} -ForegroundColor Cyan; {command}"
                           for command in commands)
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        subprocess.Popen(["powershell.exe", "-NoExit", "-NoProfile", "-EncodedCommand", encoded],
                         creationflags=subprocess.CREATE_NEW_CONSOLE)
    elif sys.platform == "darwin":
        script = " && ".join(commands).replace("\\", "\\\\").replace('"', '\\"')
        subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "{script}"',
                          "-e", 'tell application "Terminal" to activate'])


def quote_ps(text: str) -> str:
    """A PowerShell string literal of text (single quotes, which expand nothing)."""
    return "'" + text.replace("'", "''") + "'"
