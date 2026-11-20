"""The AI tools that can write the summary: finding them, remembering a path the user gave,
and calling them.

- claude:  Claude Code CLI (`claude -p`), under the login of whoever runs the tool.
- codex:   OpenAI Codex CLI (`codex exec`), logged in with ChatGPT; the "ChatGPT" choice.
- gemini:  Google Gemini CLI, logged in with a Google account.
- copilot: GitHub Copilot CLI, logged in with a GitHub account that has Copilot.
- qwen:    Qwen Code, logged in with a Qwen account.
- local:   a local model server with an OpenAI-style API: Ollama, LM Studio, Jan, GPT4All,
           llama.cpp, vLLM and others (LOCAL_SERVERS). The text stays on the computer.

Only tools with their own command line and account login are used; no API keys are asked for.

Each call keeps the person's own setup out and saves no session. A path or address entered by
the user is stored in ai.local.ini next to this file (not in git).
"""
import configparser
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

import paths
from ui_text import t

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = paths.config("ai.local.ini")
NOTES_PROMPT_FILE = os.path.join(TOOL_DIR, "summary_notes_prompt.md")
ENGINES = ["claude", "codex", "gemini", "copilot", "qwen", "local"]
TITLES = {"claude": "Claude (Claude Code)", "codex": "ChatGPT (Codex CLI)"}
# Default addresses of local model servers, in the order they are preferred; a different one can
# be entered as an address. All of them offer an OpenAI-style API (/v1/models, chat completions),
# Ollama and Msty also their own. Shared ports (8080, 8000, 5000) are named by what is most common.
LOCAL_SERVERS = {
    "http://127.0.0.1:11434": "Ollama",
    "http://127.0.0.1:1234": "LM Studio",
    "http://127.0.0.1:1337": "Jan",
    "http://127.0.0.1:4891": "GPT4All",
    "http://127.0.0.1:10000": "Msty",
    "http://127.0.0.1:5001": "KoboldCpp",
    "http://127.0.0.1:5000": "text-generation-webui / TabbyAPI",
    "http://127.0.0.1:8080": "llama.cpp / LocalAI / llamafile",
    "http://127.0.0.1:8000": "vLLM / Lemonade",
    "http://127.0.0.1:12434": "Docker Model Runner",
    "http://127.0.0.1:4000": "LiteLLM",
}
# Local models have small context windows: longer transcripts are summarized in parts of about
# this many characters (each part to notes, then the notes to the summary). ai.local.ini
# [local] chunk_chars and context override it.
LOCAL_CHUNK_CHARS = 20000
LOCAL_CONTEXT_TOKENS = 16384
LOCAL_TIMEOUT_SECONDS = 1800


def load_settings() -> configparser.ConfigParser:
    settings = configparser.ConfigParser()
    settings.read(SETTINGS_FILE, encoding="utf-8")
    return settings


def remember(engine: str, location: str) -> None:
    settings = load_settings()
    if not settings.has_section(engine):
        settings.add_section(engine)
    settings.set(engine, "path" if engine != "local" else "url", location)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as out:
        out.write("# Where the transcription tool finds the AI for summaries; written when you\n"
                  "# enter a path. Local only, not in git. Delete a line to search again.\n")
        settings.write(out)


def get_json(url: str, timeout: float = 3.0):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def port_open(url: str, timeout: float = 0.5) -> bool:
    """Quick look whether anything listens at the URL's host and port. Windows takes about two
    seconds to refuse a closed local port, so asking a server that is not there over HTTP
    made the search for installed AI tools hang for several seconds."""
    parts = urllib.parse.urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.create_connection((parts.hostname or "127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def local_models(url: str) -> list[str]:
    """Model names a local server offers; empty if nothing answers there."""
    url = url.rstrip("/")
    if not port_open(url):
        return []
    try:
        return [m["name"] for m in get_json(url + "/api/tags").get("models", [])]  # Ollama
    except (OSError, ValueError, KeyError):
        pass
    try:
        return [m["id"] for m in get_json(url + "/v1/models").get("data", [])]  # OpenAI style
    except (OSError, ValueError, KeyError):
        return []


def find_claude() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    # The native installer puts it here, which a window started before the install may not have
    # on its PATH.
    fallback = os.path.join(os.path.expanduser("~"), ".local", "bin",
                            "claude.exe" if os.name == "nt" else "claude")
    return fallback if os.path.isfile(fallback) else None


def find_npm_tool(name: str) -> str | None:
    """A tool installed with npm: on Windows its .cmd shim (the .ps1 does not start from Python),
    preferring npm's own folder, since another program may have put a same-named shim earlier on
    PATH (VS Code puts a "copilot" shim there that is not the Copilot CLI)."""
    if os.name == "nt":
        npm_folder = os.path.join(os.environ.get("APPDATA", ""), "npm", name + ".cmd")
        if os.path.isfile(npm_folder):
            return npm_folder
    for candidate in (name + ".cmd", name) if os.name == "nt" else (name,):
        found = shutil.which(candidate)
        if found and "microsoft vs code" not in found.lower():
            return found
    return None


def find_codex() -> str | None:
    found = find_npm_tool("codex")
    if found:
        return found
    # Applications opened from Finder do not inherit the PATH configured in .zprofile.
    # The official standalone installer uses ~/.local/bin; keep Homebrew as a fallback.
    if sys.platform == "darwin":
        for fallback in (os.path.expanduser("~/.local/bin/codex"),
                         "/opt/homebrew/bin/codex", "/usr/local/bin/codex"):
            if os.path.isfile(fallback):
                return fallback
    return None


# The command-line AI tools besides Claude Code and Codex: all installed with npm, each logged
# in with the person's own account (no API keys are asked for here).
CLI_TOOLS = {
    "gemini": {"title": "Gemini (Gemini CLI)", "login": "login.gemini"},
    "copilot": {"title": "GitHub Copilot (Copilot CLI)", "login": "login.copilot"},
    "qwen": {"title": "Qwen (Qwen Code)", "login": "login.qwen"},
}
TITLES.update({engine: spec["title"] for engine, spec in CLI_TOOLS.items()})


def find_engines() -> dict[str, str]:
    """Installed AI tools: engine -> executable path or server address."""
    settings = load_settings()
    found = {}
    searches = [("claude", find_claude), ("codex", find_codex)]
    searches += [(engine, lambda name=engine: find_npm_tool(name)) for engine in CLI_TOOLS]
    for engine, search in searches:
        remembered = settings.get(engine, "path", fallback=None)
        if remembered and os.path.isfile(remembered):
            found[engine] = remembered
        elif location := search():
            found[engine] = location
    remembered_url = settings.get("local", "url", fallback=None)
    candidates = ([remembered_url] if remembered_url else []) + list(LOCAL_SERVERS)
    # Asked side by side: one at a time, the closed ports would add up to several seconds.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=len(candidates)) as pool:
        answers = list(pool.map(local_models, candidates))
    for url, models in zip(candidates, answers):
        if models:
            found["local"] = url
            break
    return found


def classify(entered: str) -> tuple[str, str] | None:
    """Engine and location for a path or address the user typed, or None if it does not work."""
    entered = os.path.expanduser(entered.strip().strip('"'))
    if entered.lower().startswith(("http://", "https://")):
        return ("local", entered.rstrip("/")) if local_models(entered) else None
    tools = ["claude", "codex", *CLI_TOOLS]
    if os.path.isdir(entered):
        names = ["claude.exe", "claude.cmd"] + [tool + ".cmd" for tool in tools[1:]] + tools
        for name in names:
            if os.path.isfile(os.path.join(entered, name)):
                entered = os.path.join(entered, name)
                break
    if not os.path.isfile(entered):
        return None
    name = os.path.basename(entered).lower()
    for engine in tools:
        if name.startswith(engine):
            if name.endswith(".ps1"):  # npm's PowerShell shim; the .cmd next to it starts
                sibling = os.path.splitext(entered)[0] + ".cmd"
                entered = sibling if os.path.isfile(sibling) else entered
            return engine, entered
    return None


# Account each verified tool is logged in with, shown next to its name (engine -> text).
ACCOUNTS: dict[str, str] = {}


def title(engine: str) -> str:
    return TITLES.get(engine) or t("ai.local")


def check_login(engine: str, location: str) -> tuple[bool | None, str]:
    """Whether the tool is logged in, without sending a request to the AI: (True, account),
    (False, what to do), or (None, why it could not be told) for versions without the command."""
    if engine == "local":
        return (True, "") if local_models(location) else (False, t("login.server"))
    if engine in CLI_TOOLS:
        # None of them has a status command (Nov 2026), and their login files are not a reliable
        # sign either (keychains). A missing login shows when it is used, with how to log in.
        return None, ""
    command = [location, "auth", "status"] if engine == "claude" else [location, "login", "status"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=20, cwd=TOOL_DIR)
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, str(error)
    output = (result.stdout + result.stderr).strip()
    if engine == "claude":
        try:
            status = json.loads(result.stdout)
        except ValueError:
            return None, t("login.old_claude")
        if not status.get("loggedIn"):
            return False, t("login.claude")
        account = status.get("email") or status.get("orgName") or ""
        return True, account
    if result.returncode == 0 and "logged in" in output.lower():
        return True, output.split("using", 1)[-1].strip() if "using" in output else ""
    if "not logged in" in output.lower() or result.returncode != 0:
        return False, t("login.codex")
    return None, t("login.unknown")


def verify_engines(found: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Keeps the tools that are logged in (or whose login cannot be told); returns
    (usable engine -> location, left out engine -> reason)."""
    usable, left_out = {}, {}
    for engine, location in found.items():
        logged_in, note = check_login(engine, location)
        if logged_in is False:
            left_out[engine] = note
            continue
        usable[engine] = location
        if note and engine != "local":
            ACCOUNTS[engine] = note if logged_in else f"({note})"
    return usable, left_out


def describe(engine: str, location: str) -> str:
    if engine == "local":
        models = local_models(location)
        model = load_settings().get("local", "model", fallback=None) or (models[0] if models else "?")
        server = LOCAL_SERVERS.get(location.rstrip("/"))
        return f"{title(engine)}{f' ({server})' if server else ''}: {model} ({location})"
    account = ACCOUNTS.get(engine)
    return f"{title(engine)} — {account}" if account else title(engine)


# --- calls -----------------------------------------------------------------------------------

def run_claude(path: str, prompt: str, transcript: str) -> str:
    # The flags keep the person's own setup out of the call: no tools, no MCP servers, no user
    # settings or hooks, and no saved session holding the transcript.
    result = subprocess.run(
        [path, "-p", prompt, "--tools", "", "--strict-mcp-config",
         "--setting-sources", "project", "--no-session-persistence"],
        input=transcript, capture_output=True, text=True, encoding="utf-8", cwd=TOOL_DIR)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"claude exit {result.returncode}: {result.stderr.strip()[-500:]}")
    return result.stdout.strip()


def run_codex(path: str, prompt: str, transcript: str) -> str:
    # Everything goes through stdin, so no text passes the cmd.exe command line. The flags keep
    # the person's own config and rules out, save no session, allow no writes, and run in an
    # empty folder so nothing else is read.
    with tempfile.TemporaryDirectory() as empty:
        answer = os.path.join(empty, "answer.md")
        work = os.path.join(empty, "work")
        os.makedirs(work)
        result = subprocess.run(
            [path, "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config",
             "--ignore-rules", "--sandbox", "read-only", "--color", "never",
             "-C", work, "-o", answer, "-"],
            input=f"{prompt}\n\n<transcript>\n{transcript}\n</transcript>\n",
            capture_output=True, text=True, encoding="utf-8", cwd=work)
        text = open(answer, encoding="utf-8").read().strip() if os.path.isfile(answer) else ""
    if result.returncode != 0 or not text:
        raise RuntimeError(f"codex exit {result.returncode}: {result.stderr.strip()[-500:]}")
    return text


def cli_command(engine: str, path: str) -> list[str]:
    """Flags per tool (from their docs, Nov 2026) that keep the person's own setup out as far as
    the tool allows: no extensions, MCP servers or custom instructions, no edits or commands,
    no saved chat where it can be switched off. The text itself always goes through stdin: a
    .cmd shim limits the command line to 8191 characters and mangles quotes."""
    if engine == "gemini":
        # stdin comes first, then this short -p; the global ~/.gemini/GEMINI.md cannot be
        # switched off per call. Tools that need approval are refused in headless mode.
        return [path, "--output-format", "text", "--approval-mode", "default", "-e", "none",
                "-p", "Follow the instructions above."]
    if engine == "copilot":
        # With -p the piped input would be ignored, so everything comes through stdin.
        return [path, "-s", "--no-ask-user", "--no-custom-instructions", "--disable-builtin-mcps"]
    # qwen: --safe-mode leaves out context files, hooks, extensions, skills and MCP servers.
    return [path, "--safe-mode", "--approval-mode", "plan", "--chat-recording", "false",
            "-o", "text", "-p", "Follow the instructions above."]


def run_cli(engine: str, path: str, prompt: str, transcript: str) -> str:
    with tempfile.TemporaryDirectory() as empty:  # nothing of the person's files to read
        env = dict(os.environ, GEMINI_CLI_TRUST_WORKSPACE="true", NO_COLOR="1")
        try:
            result = subprocess.run(
                cli_command(engine, path),
                input=f"{prompt}\n\n<transcript>\n{transcript}\n</transcript>\n",
                capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=empty, env=env)
        except OSError as error:
            raise RuntimeError(f"{engine}: {error}") from error
    if result.returncode != 0 or not result.stdout.strip():
        detail = (result.stderr.strip() or result.stdout.strip())[-500:]
        raise RuntimeError(f"{engine} exit {result.returncode}: {detail}\n"
                           f"{t(CLI_TOOLS[engine]['login'])}")
    return result.stdout.strip()


def local_chat(url: str, model: str, system: str, user: str, context: int) -> str:
    url = url.rstrip("/")
    is_ollama = bool(local_models_ollama(url))
    if is_ollama:
        # Ollama's native API, so the context window can be set; its default is too small.
        endpoint, body = url + "/api/chat", {
            "model": model, "stream": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"num_ctx": context, "temperature": 0.2}}
    else:
        endpoint, body = url + "/v1/chat/completions", {
            "model": model, "stream": False, "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    request = urllib.request.Request(endpoint, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=LOCAL_TIMEOUT_SECONDS) as response:
        data = json.loads(response.read().decode("utf-8"))
    text = data["message"]["content"] if is_ollama else data["choices"][0]["message"]["content"]
    # Reasoning models may put their thinking in <think> tags; the summary is what follows.
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    return text.strip()


def local_models_ollama(url: str) -> list[str]:
    try:
        return [m["name"] for m in get_json(url + "/api/tags").get("models", [])]
    except (OSError, ValueError, KeyError):
        return []


def split_paragraphs(text: str, size: int) -> list[str]:
    parts, current = [], ""
    for paragraph in text.split("\n\n"):
        if current and len(current) + len(paragraph) > size:
            parts.append(current)
            current = ""
        current += paragraph + "\n\n"
    if current.strip():
        parts.append(current)
    return parts


def run_local(url: str, prompt: str, transcript: str, report) -> str:
    settings = load_settings()
    models = local_models(url)
    model = settings.get("local", "model", fallback=None) or (models[0] if models else None)
    if not model:
        raise RuntimeError(f"no model available at {url}")
    chunk = settings.getint("local", "chunk_chars", fallback=LOCAL_CHUNK_CHARS)
    context = settings.getint("local", "context", fallback=LOCAL_CONTEXT_TOKENS)
    if len(transcript) <= chunk:
        return local_chat(url, model, prompt, transcript, context)
    # Too long for a local model at once: notes per part, then the summary from the notes.
    notes_prompt = open(NOTES_PROMPT_FILE, encoding="utf-8").read()
    parts = split_paragraphs(transcript, chunk)
    notes = []
    for number, part in enumerate(parts, start=1):
        report(f"  part {number}/{len(parts)} to notes...")
        notes.append(local_chat(url, model, notes_prompt, part, context))
    joined = "\n\n".join(f"Notes on part {n} of {len(parts)}:\n{text}"
                         for n, text in enumerate(notes, start=1))
    report("  summary from the notes...")
    return local_chat(url, model, prompt, "The transcript was too long to read at once. Below "
                      "are detailed notes made from its consecutive parts, in order, with the "
                      "original timestamps; treat them as the transcript.\n\n" + joined, context)


def local_chunk_chars() -> int:
    return load_settings().getint("local", "chunk_chars", fallback=LOCAL_CHUNK_CHARS)


def run_single(engine: str, location: str, prompt: str, text: str) -> str:
    """One request, without splitting the text (the caller splits it if needed)."""
    if engine == "claude":
        return run_claude(location, prompt, text)
    if engine == "codex":
        return run_codex(location, prompt, text)
    if engine in CLI_TOOLS:
        return run_cli(engine, location, prompt, text)
    settings = load_settings()
    models = local_models(location)
    model = settings.get("local", "model", fallback=None) or (models[0] if models else None)
    if not model:
        raise RuntimeError(f"no model available at {location}")
    return local_chat(location, model, prompt, text,
                      settings.getint("local", "context", fallback=LOCAL_CONTEXT_TOKENS))


def run(engine: str, location: str, prompt: str, transcript: str, report=print) -> str:
    if engine == "claude":
        return run_claude(location, prompt, transcript)
    if engine == "codex":
        return run_codex(location, prompt, transcript)
    if engine in CLI_TOOLS:
        return run_cli(engine, location, prompt, transcript)
    return run_local(location, prompt, transcript, report)
