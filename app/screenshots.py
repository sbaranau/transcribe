"""Screenshots taken with a button during the live mode, and the transcript as Markdown with
each screenshot after the paragraph that was being said when it was taken.

- A screenshot is saved as screenshots/<hh-mm-ss>.png next to the recording, named by the time on
  the recording's clock, the same clock as the transcript's [hh:mm:ss] timestamps.
- write_markdown(<name>.txt) writes <name>.md next to it when such a folder is there: the same
  paragraphs, each screenshot after the paragraph whose time range holds it.

The capture uses the Windows screen (GDI) and writes PNG with zlib, so no image package is needed.
Screenshots stay on the computer; nothing here sends them anywhere.
"""
import os
import re
import struct
import sys
import zlib

import numpy as np

FOLDER = "screenshots"
NAME = re.compile(r"^(\d\d)-(\d\d)-(\d\d)(?:-(\d+))?\.png$")
PARAGRAPH_TIME = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\]")
SUPPORTED = sys.platform == "win32"


# --- screens and capture (Windows) ---------------------------------------------------------

class PhysicalPixels:
    """Within it, this thread sees every screen in its real pixels. Screens with different
    scaling (a 4K one at 150% next to a 1080p one at 100%) otherwise get coordinates scaled for
    the window's DPI, and a capture would miss part of a screen. Only the calling thread is
    switched, so the window keeps its own DPI handling."""

    def __enter__(self):
        import ctypes
        self.user = ctypes.windll.user32
        self.user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        self.user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        self.previous = self.user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # per monitor v2
        return self

    def __exit__(self, *exc):
        if self.previous:
            self.user.SetThreadDpiAwarenessContext(self.previous)


def monitors() -> list[tuple[int, int, int, int]]:
    """(left, top, right, bottom) of every screen, in physical pixels; the main screen first."""
    import ctypes
    import ctypes.wintypes as wt
    found = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)

    def on_monitor(handle, dc, rect, data):
        r = rect.contents
        found.append((r.left, r.top, r.right, r.bottom))
        return 1

    with PhysicalPixels():
        ctypes.windll.user32.EnumDisplayMonitors(None, None, callback_type(on_monitor), 0)
    # The main screen is the one at (0, 0).
    return sorted(found, key=lambda r: (r[0] != 0 or r[1] != 0, r[0], r[1]))


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """A window's rectangle in the same physical pixels as monitors()."""
    import ctypes
    import ctypes.wintypes as wt
    rect = wt.RECT()
    with PhysicalPixels():
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def all_screens(screens: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    return (min(r[0] for r in screens), min(r[1] for r in screens),
            max(r[2] for r in screens), max(r[3] for r in screens))


def capture(rect: tuple[int, int, int, int]) -> np.ndarray:
    """The screen area as an RGB array (height x width x 3)."""
    import ctypes
    import ctypes.wintypes as wt

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                    ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                    ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD)]

    with PhysicalPixels():
        return grab(rect, BITMAPINFOHEADER)


def grab(rect, BITMAPINFOHEADER) -> np.ndarray:
    import ctypes
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    left, top, right, bottom = rect
    width, height = right - left, bottom - top
    screen = user.GetDC(None)
    memory = gdi.CreateCompatibleDC(screen)
    bitmap = gdi.CreateCompatibleBitmap(screen, width, height)
    try:
        gdi.SelectObject(memory, bitmap)
        # SRCCOPY | CAPTUREBLT: layered windows (menus, tooltips, some call apps) are included.
        if not gdi.BitBlt(memory, 0, 0, width, height, screen, left, top, 0x00CC0020 | 0x40000000):
            raise OSError("the screen could not be read")
        header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        buffer = ctypes.create_string_buffer(width * height * 4)
        gdi.GetDIBits(memory, bitmap, 0, height, buffer, ctypes.byref(header), 0)
    finally:
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory)
        user.ReleaseDC(None, screen)
    return np.frombuffer(buffer.raw, dtype=np.uint8).reshape(height, width, 4)[:, :, 2::-1].copy()


def save_png(pixels: np.ndarray, path: str) -> None:
    height, width = pixels.shape[:2]
    rows = np.empty((height, width * 3 + 1), dtype=np.uint8)
    rows[:, 0] = 0  # no PNG filter
    rows[:, 1:] = pixels.reshape(height, width * 3)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows.tobytes(), 6)) + chunk(b"IEND", b""))
    with open(path + ".partial", "wb") as out:
        out.write(data)
    os.replace(path + ".partial", path)


def new_path(folder: str, seconds: float) -> str:
    """screenshots/<hh-mm-ss>.png; a second one in the same second gets -2, -3, ..."""
    shots = os.path.join(folder, FOLDER)
    os.makedirs(shots, exist_ok=True)
    seconds = int(seconds)
    stem = f"{seconds // 3600:02d}-{seconds % 3600 // 60:02d}-{seconds % 60:02d}"
    path, number = os.path.join(shots, stem + ".png"), 1
    while os.path.exists(path) or os.path.exists(path + ".partial"):
        number += 1
        path = os.path.join(shots, f"{stem}-{number}.png")
    return path


# --- Markdown ---------------------------------------------------------------------------------

def shots_in(folder: str) -> list[tuple[int, str]]:
    """(seconds, file name) of the screenshots in <folder>/screenshots, in time order."""
    shots = os.path.join(folder, FOLDER)
    if not os.path.isdir(shots):
        return []
    found = []
    for name in os.listdir(shots):
        match = NAME.match(name)
        if match:
            hours, minutes, seconds, number = match.groups()
            found.append((int(hours) * 3600 + int(minutes) * 60 + int(seconds), int(number or 1), name))
    return [(seconds, name) for seconds, _, name in sorted(found)]


def clock(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def paragraph_markdown(paragraph: str) -> str:
    """"[00:01:10] Speaker 1: text" -> "**[00:01:10] Speaker 1:** text"; the tool's "# ..." header
    lines become a note instead of a heading."""
    if paragraph.startswith("# "):
        return "_" + paragraph[2:].strip() + "_"
    match = re.match(r"^(\[\d\d:\d\d:\d\d\]\s+(?:[^:\n\[\]]{1,40}:)?)(.*)$", paragraph, re.S)
    text = paragraph
    if match:
        text = f"**{match.group(1).strip()}** {match.group(2).strip()}"
    return re.sub(r"(?m)^([#>*+-]|\d+\.)", r"\\\1", text) if not match else text


def write_markdown(txt_path: str, md_path: str | None = None) -> str | None:
    """<name>.md next to <name>.txt with the screenshots of that folder put in; None when there
    are no screenshots."""
    folder = os.path.dirname(os.path.abspath(txt_path))
    shots = shots_in(folder)
    if not shots:
        return None
    md_path = md_path or os.path.splitext(txt_path)[0] + ".md"
    paragraphs = [p.strip() for p in open(txt_path, encoding="utf-8").read().split("\n\n") if p.strip()]
    starts = []
    for paragraph in paragraphs:
        match = PARAGRAPH_TIME.match(paragraph)
        starts.append(int(match[1]) * 3600 + int(match[2]) * 60 + int(match[3]) if match else None)
    # Each screenshot goes after the last paragraph that started at or before it; one taken
    # before the first paragraph goes before it.
    after = {}
    before_all = []
    for seconds, name in shots:
        index = None
        for number, start in enumerate(starts):
            if start is not None and start <= seconds:
                index = number
        (before_all if index is None else after.setdefault(index, [])).append((seconds, name))

    def picture(seconds: int, name: str) -> str:
        return f"![{clock(seconds)}]({FOLDER}/{name})"

    blocks = [picture(*shot) for shot in before_all]
    for number, paragraph in enumerate(paragraphs):
        blocks.append(paragraph_markdown(paragraph))
        blocks += [picture(*shot) for shot in after.get(number, [])]
    with open(md_path, "w", encoding="utf-8") as out:
        out.write("\n\n".join(blocks) + "\n")
    return md_path


def write_markdown_for(txt_paths: list[str], report=print) -> list[str]:
    """Markdown for every transcript file given that exists, when its folder has screenshots."""
    written = []
    for path in txt_paths:
        if os.path.isfile(path):
            md = write_markdown(path)
            if md:
                written.append(md)
    if written:
        report("With screenshots: " + ", ".join(os.path.basename(p) for p in written))
    return written
