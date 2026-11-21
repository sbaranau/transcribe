"""The look of the window: the Sun Valley ttk theme (sv-ttk, Windows 11 Fluent style, also used
on macOS and Linux) in light or dark, as the system is set, and one palette that every coloured
widget of live_gui takes its colours from. Plain tk widgets (labels, frames, text fields) get the
palette's defaults through Tk's option database, so they follow the theme without each one
naming its colours.
"""
import ctypes
import os
import subprocess
import sys
from types import SimpleNamespace

# "Calm ink-blue": the neutrals carry a slight blue-slate tint (cool paper white, deep slate navy)
# and a deep indigo app bar gives the window its identity; sv-ttk's blue accent belongs to the same
# family. Every text colour has a WCAG contrast of at least 4.5:1 on its background.
LIGHT = dict(
    bg="#f3f6fb", surface="#ffffff", border="#d9e1ec", text="#172033", muted="#556274",
    accent="#005fb8", link="#0057a8", on_accent="#ffffff",
    success="#11743a", success_bg="#e2f5e9", success_border="#9fd6b3",
    error="#c0262d", error_bg="#fdecec", error_border="#f2b2b5",
    warn_bg="#fff5d6", warn_text="#6a4a00", warn_border="#f0d27a",
    info_bg="#e6f0fc", info_text="#0b4a8f", neutral_bg="#edf1f7",
    field="#ffffff", field_alt="#f5f8fc", selection="#cfe2fa", track="#dde4ee",
    draft_bg="#eef3f9", record="#c42b1c",
    voices=["#0b7a4b", "#b3206b", "#a85200", "#6b3fc4", "#00788a", "#7a5a3c"],
    header_bg="#14306b", header_text="#ffffff", header_muted="#b9c8e6", header_hover="#21418a",
    card_icon_bg="#eaf1fc",
)
DARK = dict(
    bg="#151a23", surface="#1e2531", border="#2f3a4a", text="#eef2f8", muted="#9aa7ba",
    accent="#57c8ff", link="#6cc6ff", on_accent="#000000",
    success="#6fd38a", success_bg="#17301f", success_border="#2f6140",
    error="#ff9aa2", error_bg="#3d1f24", error_border="#74363e",
    warn_bg="#3a2f14", warn_text="#ffd866", warn_border="#6b5a2a",
    info_bg="#172b45", info_text="#a6d4ff", neutral_bg="#252d3a",
    field="#10151d", field_alt="#1a212c", selection="#24476e", track="#2c3646",
    draft_bg="#1d2532", record="#ff6b6b",
    voices=["#6fd38a", "#f48fb8", "#ffb366", "#c9a2ff", "#4dd6e6", "#d4b8a0"],
    header_bg="#1b2a45", header_text="#f3f6fb", header_muted="#a9b8d3", header_hover="#26385a",
    card_icon_bg="#22324a",
)

# Headings carry a small icon from the system's icon font (Windows 11: Segoe Fluent Icons,
# Windows 10: Segoe MDL2 Assets, same code points); elsewhere they have none.
ICON_FONT = None
GLYPHS = {"settings": "\ue713", "page": "\ue8a5", "results": "\ue9d5", "transcript": "\ue8bd",
          "translation": "\ue8c1", "history": "\ue81c", "ai": "\ue99a",
          "more": "\ue712"}
COPYRIGHT = "© 2026 sbaranau · MIT License"


def glyph(name: str) -> str:
    return GLYPHS.get(name, "") if ICON_FONT else ""


# The current palette; apply() fills it. live_gui reads it when it builds its widgets.
C = SimpleNamespace(dark=False, **LIGHT)


def system_is_dark() -> bool:
    """Whether the system uses a dark appearance for apps (read once, at start).
    TRANSCRIBE_THEME=light or dark overrides it."""
    forced = os.environ.get("TRANSCRIBE_THEME", "").lower()
    if forced in ("light", "dark"):
        return forced == "dark"
    try:
        if os.name == "nt":
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
        if sys.platform == "darwin":
            result = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                                    capture_output=True, text=True, timeout=3)
            return result.stdout.strip().lower() == "dark"
    except (OSError, subprocess.SubprocessError):
        pass
    return False


def apply(root, font: str) -> SimpleNamespace:
    """Sets the theme on a new Tk root and returns the palette (also in theme.C)."""
    global ICON_FONT
    from tkinter import font as tkfont
    families = set(tkfont.families(root))
    ICON_FONT = next((name for name in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if name in families), None)
    dark = system_is_dark()
    C.__dict__.update(DARK if dark else LIGHT, dark=dark)
    try:
        import sv_ttk
        sv_ttk.set_theme("dark" if dark else "light", root)
        # The theme's own background and text colour become the palette's, so the space around
        # its buttons and fields is the window's colour, not sv-ttk's grey.
        name = "sv_dark" if dark else "sv_light"
        root.tk.call("set", f"ttk::theme::{name}::colors(-bg)", C.bg)
        root.tk.call("set", f"ttk::theme::{name}::colors(-fg)", C.text)
        # sv-ttk sets its colours on <<ThemeChanged>>, which does not reach a window that is
        # not shown yet: then frames and labels keep Tk's light grey. Called directly instead.
        root.tk.call("configure_colors")
        # ...and only this once: later, on <<ThemeChanged>> (which Tk 9, as on macOS, sends when
        # the window is shown), the handler calls tk_setPalette, which in Tk 9 repaints every
        # widget, so the app bar, cards and captions lost their own colours.
        root.tk.call("bind", root.winfo_class(), "<<ThemeChanged>>", "")
        recolor_card(root, name)
    except Exception as error:  # an installation without it keeps the system theme
        print(f"Theme not applied: {error}", flush=True)
    for widget in ("Label", "Frame", "Canvas", "Toplevel", "Checkbutton", "Radiobutton", "Message"):
        root.option_add(f"*{widget}.background", C.bg)
        root.option_add(f"*{widget}.foreground", C.text)
    # Entry fields take their font from the widget, not the style: the same size as the labels.
    for widget in ("TCombobox", "TEntry", "TSpinbox"):
        root.option_add(f"*{widget}.font", (font, 10))
    root.option_add("*TCombobox*Listbox.font", (font, 10))
    root.option_add("*Text.background", C.field)
    root.option_add("*Text.foreground", C.text)
    root.option_add("*Menu.background", C.surface)
    root.option_add("*Menu.foreground", C.text)
    root.option_add("*Menu.activeBackground", C.selection)
    root.option_add("*Menu.activeForeground", C.text)
    root.configure(background=C.bg)
    from tkinter import ttk
    style = ttk.Style(root)
    style.configure("TLabel", font=(font, 10))
    style.configure("TCheckbutton", font=(font, 10))
    style.configure("TButton", font=(font, 10))
    style.configure("Head.TLabel", font=(font, 17, "bold"))
    style.configure("Column.TLabel", font=(font, 11, "bold"))
    style.configure("TLabelframe.Label", font=(font, 11, "bold"), foreground=C.text)
    style.configure("Note.TLabel", foreground=C.muted, font=(font, 9))
    style.configure("Big.TButton", font=(font, 11, "bold"), padding=(16, 8))
    # As high as a Big.Accent.TButton, for secondary actions beside it.
    style.configure("Tall.TButton", font=(font, 10), padding=(16, 11))
    style.configure("Accent.TButton", font=(font, 10, "bold"))
    style.configure("Big.Accent.TButton", font=(font, 12, "bold"), padding=(20, 10))
    style.configure("Huge.Accent.TButton", font=(font, 14, "bold"), padding=(24, 14))
    title_bar(root)
    return C


def recolor_card(root, name: str) -> None:
    """sv-ttk draws a section's frame (ttk.LabelFrame) with a picture filled in its own grey; the
    widgets inside have the palette's background, which showed as patches. The inside of that
    picture is filled with the palette's background, keeping its rounded 1-pixel outline."""
    image = root.tk.call("set", f"ttk::theme::{name}::I(card)")
    width, height = int(root.tk.call("image", "width", image)), int(root.tk.call("image", "height", image))
    # Three rectangles inside the outline, leaving the rounded corners alone.
    for x1, y1, x2, y2 in ((1, 4, width - 1, height - 4), (4, 1, width - 4, height - 1),
                           (2, 2, width - 2, height - 2)):
        root.tk.call(image, "put", C.bg, "-to", x1, y1, x2, y2)


def title_bar(window) -> None:
    """A dark title bar on Windows 10/11 in dark mode (macOS does this by itself)."""
    if os.name != "nt" or not C.dark:
        return
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE; 19 before Windows 10 20H1
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value),
                                                         ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass  # only looks
