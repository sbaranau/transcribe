"""Setting up an AI for the check and the summary, for people who have never used a terminal:
the window (live_gui.AiSetupDialog) asks which account they have, Claude or ChatGPT, and one
button runs the official installer and the sign-in in a visible PowerShell (Windows) or Terminal
(macOS) window. Every step says in plain words what happens; the browser opens for the sign-in.
The window watches meanwhile and says when the AI is ready.

Only Claude Code and the Codex CLI are offered: both install for the current user and sign in
with the person's own account, so no API key is asked for. The other tools ai_engines finds
(Gemini CLI, Copilot CLI, Qwen Code, local servers) still work when installed some other way.
"""
import os
import shlex
import subprocess
import sys
import tempfile

import ai_engines
from ui_text import t

# Per AI: the steps as (what the shell window says, command), and a file that must exist after
# the installation. A later command must not rely on a PATH that an earlier one changed (the
# running shell does not see it), hence the full paths.
if os.name == "nt":
    GUIDES = {
        "claude": {
            "steps": [("install.do_claude", "irm https://claude.ai/install.ps1 | iex"),
                      ("install.do_login", '& "$env:USERPROFILE\\.local\\bin\\claude.exe" auth login')],
            "check": "$env:USERPROFILE\\.local\\bin\\claude.exe",
        },
        "codex": {
            "steps": [("install.do_node", "winget install --id OpenJS.NodeJS.LTS -e --source winget"),
                      ("install.do_codex", '& "$env:ProgramFiles\\nodejs\\npm.cmd" install -g @openai/codex'),
                      ("install.do_login", '& "$env:APPDATA\\npm\\codex.cmd" login')],
            "check": "$env:APPDATA\\npm\\codex.cmd",
        },
    }
elif sys.platform == "darwin":
    PROFILE_PATH = ("grep -q '.local/bin' ~/.zprofile 2>/dev/null || "
                    "echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> ~/.zprofile")
    GUIDES = {
        "claude": {
            "steps": [("install.do_claude", "curl -fsSL https://claude.ai/install.sh | bash"),
                      ("install.do_path", PROFILE_PATH),
                      ("install.do_login", "~/.local/bin/claude auth login")],
            "check": "~/.local/bin/claude",
        },
        "codex": {
            "steps": [("install.do_codex", "curl -fsSL https://chatgpt.com/codex/install.sh | sh"),
                      ("install.do_path", PROFILE_PATH),
                      ("install.do_login", "~/.local/bin/codex login")],
            "check": "~/.local/bin/codex",
        },
    }
else:
    GUIDES = {}

SIGN_UP = {"claude": "https://claude.ai", "codex": "https://chatgpt.com"}
SHELL = "PowerShell" if os.name == "nt" else "Terminal"


def status(engine: str) -> tuple[str, str]:
    """("missing" | "login" | "ready", account) for claude or codex, as it is now."""
    location = ai_engines.find_claude() if engine == "claude" else ai_engines.find_codex()
    if not location:
        return "missing", ""
    logged_in, note = ai_engines.check_login(engine, location)
    if logged_in is False:
        return "login", ""
    return "ready", note if logged_in else ""


def run(engine: str, login_only: bool = False) -> None:
    """Opens a new PowerShell or Terminal window that installs the AI and signs in, saying each
    step in the interface language, and stays open so everything can be read."""
    guide = GUIDES[engine]
    steps = guide["steps"][-1:] if login_only else guide["steps"]
    total = len(steps)
    name = t("install.claude_name") if engine == "claude" else t("install.codex_name")
    if os.name == "nt":
        import base64
        lines = [f"$Host.UI.RawUI.WindowTitle = {quote_ps('Live Transcription: ' + name)}",
                 f"Write-Host {quote_ps(t('install.shell_intro', name=name))} -ForegroundColor Yellow"]
        for number, (what, command) in enumerate(steps, start=1):
            if what == "install.do_login":
                # Nothing to sign in with if the installation failed: say so instead.
                lines.append(f'if (-not (Test-Path "{guide["check"]}")) {{ '
                             f"Write-Host {quote_ps(t('install.shell_failed'))} -ForegroundColor Red; return }}")
            step = t("install.shell_step", n=number, total=total, what=t(what))
            lines.append(f"Write-Host ''; Write-Host {quote_ps(step)} -ForegroundColor Cyan")
            lines.append(command)
        lines.append(f"Write-Host ''; Write-Host {quote_ps(t('install.shell_done'))} -ForegroundColor Green")
        encoded = base64.b64encode("\n".join(lines).encode("utf-16-le")).decode("ascii")
        subprocess.Popen(["powershell.exe", "-NoExit", "-NoProfile", "-EncodedCommand", encoded],
                         creationflags=subprocess.CREATE_NEW_CONSOLE)
    elif sys.platform == "darwin":
        lines = [f"printf '\\033]0;%s\\007' {shlex.quote('Live Transcription: ' + name)}",
                 f"echo {shlex.quote(t('install.shell_intro', name=name))}"]
        for number, (what, command) in enumerate(steps, start=1):
            if what == "install.do_login":
                lines.append(f"[ -x {guide['check']} ] || {{ echo {shlex.quote(t('install.shell_failed'))}; exit 1; }}")
            step = t("install.shell_step", n=number, total=total, what=t(what))
            lines.append(f"echo; echo {shlex.quote(step)}")
            lines.append(command)
        lines.append(f"echo; echo {shlex.quote(t('install.shell_done'))}")
        script = os.path.join(tempfile.gettempdir(), f"live-transcription-{engine}.sh")
        with open(script, "w", encoding="utf-8") as out:
            out.write("\n".join(lines) + "\n")
        subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "bash {script}"',
                          "-e", 'tell application "Terminal" to activate'])


def commands(engine: str) -> list[str]:
    return [command for _, command in GUIDES[engine]["steps"]]


def quote_ps(text: str) -> str:
    """A PowerShell string literal of text (single quotes, which expand nothing)."""
    return "'" + text.replace("'", "''") + "'"
