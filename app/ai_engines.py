"""The AI tools that can write the summary: finding them, remembering a path the user gave,
and calling them.

- claude: Claude Code CLI (`claude -p`), under the login of whoever runs the tool.
- codex:  OpenAI Codex CLI (`codex exec`), logged in with ChatGPT; the "ChatGPT" choice.
- local:  a local model server with an OpenAI-style API: Ollama, LM Studio, Jan, llama.cpp
          and others. The text stays on the computer.

Each call keeps the person's own setup out and saves no session. A path or address entered by
the user is stored in ai.local.ini next to this file (not in git).
"""
import configparser
import json
import os
import shutil
import socket
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(TOOL_DIR, "ai.local.ini")
NOTES_PROMPT_FILE = os.path.join(TOOL_DIR, "summary_notes_prompt.md")
ENGINES = ["claude", "codex", "local"]
TITLES = {"claude": "Claude (Claude Code)", "codex": "ChatGPT (Codex CLI)", "local": "локальная модель"}
# Default ports of local model servers; a different one can be entered as an address.
LOCAL_SERVERS = ["http://127.0.0.1:11434", "http://127.0.0.1:1234"]  # Ollama, LM Studio
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


def find_codex() -> str | None:
    # npm installs codex, codex.cmd and codex.ps1; only the .cmd starts from Python.
    found = shutil.which("codex.cmd") or shutil.which("codex")
    return found


def find_engines() -> dict[str, str]:
    """Installed AI tools: engine -> executable path or server address."""
    settings = load_settings()
    found = {}
    for engine, search in (("claude", find_claude), ("codex", find_codex)):
        remembered = settings.get(engine, "path", fallback=None)
        if remembered and os.path.isfile(remembered):
            found[engine] = remembered
        elif location := search():
            found[engine] = location
    remembered_url = settings.get("local", "url", fallback=None)
    for url in ([remembered_url] if remembered_url else []) + LOCAL_SERVERS:
        if local_models(url):
            found["local"] = url
            break
    return found


def classify(entered: str) -> tuple[str, str] | None:
    """Engine and location for a path or address the user typed, or None if it does not work."""
    entered = entered.strip().strip('"')
    if entered.lower().startswith(("http://", "https://")):
        return ("local", entered.rstrip("/")) if local_models(entered) else None
    if os.path.isdir(entered):
        for name in ("claude.exe", "codex.cmd", "claude.cmd", "claude", "codex"):
            if os.path.isfile(os.path.join(entered, name)):
                entered = os.path.join(entered, name)
                break
    if not os.path.isfile(entered):
        return None
    name = os.path.basename(entered).lower()
    if name.startswith("claude"):
        return "claude", entered
    if name.startswith("codex"):
        if name.endswith(".ps1"):
            sibling = os.path.splitext(entered)[0] + ".cmd"
            entered = sibling if os.path.isfile(sibling) else entered
        return "codex", entered
    return None


# Account each verified tool is logged in with, shown next to its name (engine -> text).
ACCOUNTS: dict[str, str] = {}


def check_login(engine: str, location: str) -> tuple[bool | None, str]:
    """Whether the tool is logged in, without sending a request to the AI: (True, account),
    (False, what to do), or (None, why it could not be told) for versions without the command."""
    if engine == "local":
        return (True, "") if local_models(location) else (False, "сервер не отвечает")
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
            return None, "вход не проверен (старая версия Claude Code)"
        if not status.get("loggedIn"):
            return False, "вход не выполнен: запустите claude и войдите (/login)"
        account = status.get("email") or status.get("orgName") or ""
        return True, account
    if result.returncode == 0 and "logged in" in output.lower():
        return True, output.split("using", 1)[-1].strip() if "using" in output else ""
    if "not logged in" in output.lower() or result.returncode != 0:
        return False, "вход не выполнен: выполните codex login"
    return None, "вход не проверен"


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
        return f"{TITLES[engine]}: {model} ({location})"
    account = ACCOUNTS.get(engine)
    return f"{TITLES[engine]} — {account}" if account else TITLES[engine]


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
    return run_local(location, prompt, transcript, report)
