"""A quiet GitHub Releases update check for packaged builds."""
import json
import os
import urllib.request

LATEST_RELEASE_API = "https://api.github.com/repos/sbaranau/transcribe/releases/latest"
RELEASES_URL = "https://github.com/sbaranau/transcribe/releases/latest"


def _parts(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.strip().lstrip("v").split(".") if part.isdigit())


def current_version() -> str:
    configured = os.environ.get("TRANSCRIBE_VERSION_FILE")
    candidates = [configured] if configured else []
    candidates.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION"))
    for path in candidates:
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8") as source:
                return source.read().strip()
    return "0"


def latest_release() -> str | None:
    request = urllib.request.Request(LATEST_RELEASE_API, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "Live-Transcription-update-check"})
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            return json.load(response).get("tag_name") or None
    except (OSError, ValueError, KeyError):
        return None


def is_newer(version: str) -> bool:
    return _parts(version) > _parts(current_version())


def newer_release() -> str | None:
    version = latest_release()
    return version if version and is_newer(version) else None
