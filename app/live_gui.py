"""The window of the live mode (live-transcribe), in the interface language (ui_text.py).

1. Before: interface language, meeting language, microphone and output devices, folder; the
   model loads meanwhile. Changing the interface language rebuilds the window, keeping the model.
2. During: recording light and timer, sound levels of the microphone and the computer, the text
   with timestamps (auto-scrolling unless you scrolled up), the unfinished phrase as a grey draft;
   with a translation chosen, the translation in a second column (translator.LiveTranslator);
   Stop, screenshot (screenshots.py; a mark in the text after the paragraph it belongs to), open
   folder, copy text, text size.
3. After: the full processing as check boxes (transcribe again, speakers, check, summary, which
   AI, delete the sound), its progress, and buttons to open the results. The processing runs as
   a child process, so it can be stopped; its settings are locked meanwhile.

All work runs in background threads; they talk to the window only through a queue that the
window reads every 100 ms.
"""
import ctypes
import gc
import glob
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

import ai_engines
import live
import screenshots
import transcribe as tool
import translator
import ui_text
from ui_text import t

# Stored in ui.local.ini for "do not record the microphone", whatever the interface language.
NO_MICROPHONE = "<none>"
OLD_NO_MICROPHONE = "Не записывать микрофон"  # what versions before 2026-11-13 stored
# The language and microphone chosen last time are offered again (local, not in git).
UI_SETTINGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.local.ini")
PARAGRAPH_PAUSE = 2.0
PARAGRAPH_LONGEST = 30.0
GREY, RED, GREEN = "#6b6b6b", "#c62828", "#2e7d32"
TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
ICONS = os.path.join(TOOL_DIR, "icons")
# Segoe UI on Windows; on Linux the first of these the system has (set in run()).
FONT = "Segoe UI"
LINUX_FONTS = ["Ubuntu", "Noto Sans", "DejaVu Sans", "Liberation Sans"]
# Label colours for the voices of the other side (blue is kept for you).
VOICE_COLOURS = ["#2e7d32", "#c2185b", "#ef6c00", "#6a1b9a", "#00838f", "#8d6e63"]


class App:
    def __init__(self, root: tk.Tk, args, loaded=None):
        """loaded: (model, hotwords) kept from the window this one replaces."""
        self.root, self.args = root, args
        self.restart = None  # set to (model, hotwords) when the interface language changes
        self.processing = None  # the child process of the full processing while it runs
        self.live_translator = None
        self.translation_prepare_id = 0
        self.translation_loading = False
        self.translation_loading_pair = None
        self.translation_text = None
        self.translation_column = None
        self.pending_shots = []  # (seconds, path) whose mark waits for the end of its paragraph
        self.shot_count = 0
        self.shot_savers = []
        self.cancelled = False
        self.events = queue.Queue()
        self.model = self.hotwords = self.session = None
        self.levels = (0.0, 0.0)
        self.paragraph_start = self.last_end = self.last_label = None
        self.drafts = {}  # label -> unfinished phrase
        self.found_ai = {}
        self.text_size = 13
        self.base_folder = os.path.join(live.documents_folder(), "Transcripts")
        if args.out_dir:
            self.base_folder = args.out_dir

        root.title(t("win.title"))
        set_icon(root)
        root.geometry("900x760")
        root.minsize(640, 520)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        style = ttk.Style()
        style.configure("Big.TButton", font=(FONT, 11, "bold"), padding=(14, 6))
        style.configure("TLabel", font=(FONT, 10))
        style.configure("TCheckbutton", font=(FONT, 10))
        style.configure("Head.TLabel", font=(FONT, 14, "bold"))
        style.configure("Column.TLabel", font=(FONT, 11, "bold"))
        style.configure("Note.TLabel", foreground=GREY, font=(FONT, 9))

        self.build_header()
        self.setup_frame = self.build_setup()
        self.meters_frame = self.build_meters()
        self.text_frame = self.build_text()
        self.controls_frame = self.build_controls()
        self.after_frame = None
        self.setup_frame.pack(fill="x", padx=14, pady=(0, 8))
        self.text_frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        if loaded:
            self.events.put(("model", (*loaded, "")))
        else:
            threading.Thread(target=self.load_model, daemon=True).start()
        root.after(100, self.poll)

    # --- layout -----------------------------------------------------------------------------------

    def build_header(self) -> None:
        bar = ttk.Frame(self.root, padding=(14, 12, 14, 8))
        bar.pack(fill="x")
        title_box = ttk.Frame(bar)
        title_box.pack(side="left")
        ttk.Label(title_box, text=t("win.title"), style="Head.TLabel").pack(anchor="w")
        ttk.Label(title_box, text=t("win.subtitle"), style="Note.TLabel").pack(anchor="w", pady=(1, 0))
        # Top right, before the recording only: a change rebuilds the window around the loaded
        # model, so it is usable once the model is there.
        self.interface_box = ttk.Frame(bar)
        self.interface_box.pack(side="right")
        ttk.Label(self.interface_box, text=t("win.interface"), style="Note.TLabel").pack(side="left", padx=(0, 6))
        self.interface = ttk.Combobox(self.interface_box, state="disabled", width=10,
                                      values=list(ui_text.LANGUAGES.values()))
        self.interface.current(list(ui_text.LANGUAGES).index(ui_text.language()))
        self.interface.bind("<<ComboboxSelected>>", self.change_interface)
        self.interface.pack(side="left")
        self.timer = ttk.Label(bar, text="", font=(FONT, 14))
        self.timer.pack(side="right")
        self.status = ttk.Label(bar, text=t("win.loading"), foreground=GREY,
                                font=(FONT, 11))
        self.status.pack(side="right", padx=16)

    def build_setup(self) -> ttk.Frame:
        frame = ttk.LabelFrame(self.root, text=t("win.before"), padding=12)
        frame.columnconfigure(1, weight=1)
        self.advanced_visible = False
        self.advanced_widgets = []

        remembered = self.load_ui_settings()
        if not self.args.out_dir and remembered.get("folder"):
            self.base_folder = os.path.abspath(os.path.expanduser(remembered["folder"]))
        self.languages = [(None, t("meeting.auto"))] + ui_text.meeting_languages()
        ttk.Label(frame, text=t("win.language")).grid(row=0, column=0, sticky="w", pady=3)
        self.language = ttk.Combobox(frame, state="readonly", values=[name for _, name in self.languages], width=34)
        wanted = self.args.language or remembered.get("language") or None
        default = next((i for i, (code, _) in enumerate(self.languages) if code == wanted), 0)
        self.language.current(default)
        self.language.bind("<<ComboboxSelected>>", self.prepare_translation)
        self.language.grid(row=0, column=1, sticky="w", pady=3)

        # Translation while it happens: none, or into one of the interface languages.
        self.targets = [(None, t("win.translate_none"))] + ui_text.meeting_languages()[:3]
        ttk.Label(frame, text=t("win.translate_to")).grid(row=1, column=0, sticky="nw", pady=(6, 3))
        line = ttk.Frame(frame)
        line.grid(row=1, column=1, sticky="w", pady=3)
        self.translate_to = ttk.Combobox(line, state="readonly", values=[name for _, name in self.targets], width=34)
        wanted = remembered.get("translate") or None
        self.translate_to.current(next((i for i, (code, _) in enumerate(self.targets) if code == wanted), 0))
        self.translate_to.bind("<<ComboboxSelected>>", self.prepare_translation)
        self.translate_to.pack(anchor="w")
        self.translation_note = ttk.Label(line, text=t("win.translate_note"), style="Note.TLabel", wraplength=520)
        self.translation_note.pack(anchor="w", pady=(2, 0))
        self.translation_progress = ttk.Progressbar(
            line, mode="determinate" if sys.platform == "darwin" else "indeterminate", length=300)

        microphones, default_microphone, speakers = live.list_devices()
        self.has_computer_audio = bool(speakers)
        self.microphones = {m.name: m for m in microphones}
        ttk.Label(frame, text=t("win.microphone")).grid(row=2, column=0, sticky="w", pady=3)
        self.microphone = ttk.Combobox(frame, state="readonly", width=50,
                                       values=list(self.microphones) + [t("win.no_microphone")])
        last_microphone = remembered.get("microphone")
        if last_microphone in self.microphones:
            self.microphone.set(last_microphone)
        elif last_microphone in (NO_MICROPHONE, OLD_NO_MICROPHONE) or not default_microphone:
            self.microphone.set(t("win.no_microphone"))
        else:
            self.microphone.set(default_microphone.name)
        self.microphone.grid(row=2, column=1, sticky="w", pady=3)

        self.speakers = []
        self.speaker_buttons = []
        if speakers:
            ttk.Label(frame, text=t("win.computer")).grid(row=3, column=0, sticky="nw", pady=3)
            box = ttk.Frame(frame)
            box.grid(row=3, column=1, sticky="w", pady=3)
            for speaker in speakers:
                var = tk.BooleanVar(value=True)
                button = ttk.Checkbutton(box, text=speaker.name, variable=var)
                button.pack(anchor="w")
                self.speaker_buttons.append(button)
                self.speakers.append((speaker, var))
            ttk.Label(box, text=t("win.all_devices"),
                      style="Note.TLabel", wraplength=520).pack(anchor="w")

        # Screenshots with a button during the recording: of which screen.
        self.screens = []
        if screenshots.SUPPORTED:
            try:
                found = screenshots.monitors()
            except Exception:
                found = []
            self.screens = [(t("win.screen_n", n=n, w=r[2] - r[0], h=r[3] - r[1]), r)
                            for n, r in enumerate(found, start=1)]
            if len(found) > 1:
                self.screens.append((t("win.screen_all"), screenshots.all_screens(found)))
        if self.screens:
            screen_label = ttk.Label(frame, text=t("win.shots_of"))
            screen_label.grid(row=5, column=0, sticky="nw", pady=(6, 3))
            line = ttk.Frame(frame)
            line.grid(row=5, column=1, sticky="w", pady=3)
            self.screen_choice = ttk.Combobox(line, state="readonly", width=34,
                                              values=[name for name, _ in self.screens])
            wanted = remembered.get("screen", "")
            self.screen_choice.current(int(wanted) if wanted.isdigit() and int(wanted) < len(self.screens) else 0)
            self.screen_choice.pack(anchor="w")
            ttk.Label(line, text=t("win.shots_note"), style="Note.TLabel", wraplength=520).pack(anchor="w", pady=(2, 0))
            self.advanced_widgets.extend((screen_label, line))

        folder_label = ttk.Label(frame, text=t("win.folder"))
        folder_label.grid(row=6, column=0, sticky="w", pady=3)
        folder_line = ttk.Frame(frame)
        folder_line.grid(row=6, column=1, sticky="ew", pady=3)
        self.folder_var = tk.StringVar(value=self.base_folder)
        self.folder_entry = ttk.Entry(folder_line, textvariable=self.folder_var, width=52)
        self.folder_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(folder_line, text=t("win.choose_folder"), command=self.choose_base_folder).pack(
            side="left", padx=(6, 0))
        ttk.Label(folder_line, text=t("win.date_time"), style="Note.TLabel").pack(side="left", padx=(6, 0))
        self.advanced_widgets.extend((folder_label, folder_line))

        self.advanced_button = ttk.Button(
            frame, text="▸  " + t("win.advanced"), command=self.toggle_advanced)
        self.advanced_button.grid(row=4, column=0, columnspan=2, sticky="w", pady=(7, 2))
        for widget in self.advanced_widgets:
            widget.grid_remove()

        tk.Label(
            frame, text=t("win.tell_people"), background="#fff3c4", foreground="#5d4300",
            font=(FONT, 10), anchor="w", padx=10, pady=7).grid(
                row=7, column=0, columnspan=2, sticky="ew", pady=(10, 4))
        # The native macOS ttk button is deliberately subdued and ignores custom background
        # colours. This is the primary action, so use a classic button with an explicit treatment.
        self.start_button = tk.Button(
            frame, text=t("win.start"), command=self.start, state="disabled",
            font=(FONT, 14, "bold"), background=RED, foreground="white",
            activebackground="#a91f1f", activeforeground="white",
            disabledforeground="#777777",
            relief="flat", borderwidth=0, padx=24, pady=10, cursor="hand2")
        self.start_button.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(10, 2))
        return frame

    def toggle_advanced(self) -> None:
        self.advanced_visible = not self.advanced_visible
        for widget in self.advanced_widgets:
            widget.grid() if self.advanced_visible else widget.grid_remove()
        self.advanced_button.configure(
            text=("▾  " if self.advanced_visible else "▸  ") + t("win.advanced"))

    def choose_base_folder(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self.root, initialdir=self.folder_var.get() or self.base_folder,
            title=t("win.choose_folder"))
        if chosen:
            self.folder_var.set(chosen)

    def prepare_translation(self, _event=None) -> None:
        """Download the selected language pair before recording, once, in the background."""
        source = self.languages[self.language.current()][0]
        target = self.targets[self.translate_to.current()][0]
        pair = (source, target)
        if self.translation_loading and pair == self.translation_loading_pair:
            return
        self.translation_prepare_id += 1
        request_id = self.translation_prepare_id
        self.translation_loading = False
        self.translation_loading_pair = None
        if not target:
            self.translation_note.configure(text=t("win.translate_note"), foreground=GREY)
            self.refresh_start_button()
            return
        if source not in translator.LANGUAGES:
            self.translation_note.configure(text=t("win.translate_choose_source"), foreground=GREY)
            self.refresh_start_button()
            return
        directions = translator.route(source, target)
        if not directions or all(translator.is_downloaded(direction) for direction in directions):
            self.translation_note.configure(text=t("win.translate_ready"), foreground=GREEN)
            self.refresh_start_button()
            return
        self.translation_loading = True
        self.translation_loading_pair = pair
        self.translation_expected_mb = 440 * len(directions)
        self.translation_progress.configure(maximum=self.translation_expected_mb, value=0)
        self.translation_note.configure(text=t("win.translate_loading"), foreground=GREY)
        self.set_translation_busy(True)
        self.refresh_start_button()

        def download() -> None:
            try:
                completed = 0
                for direction in directions:
                    if not translator.is_downloaded(direction):
                        translator.download(
                            direction, report=lambda message: print(message, flush=True),
                            progress=lambda size, base=completed: self.events.put(
                                ("translation_progress", (request_id, base + size))))
                    completed += sum(os.path.getsize(os.path.join(translator.folder_of(direction), name))
                                     for name in translator.FILES)
                self.events.put(("translation_prepared", (request_id, None)))
            except Exception as error:
                import traceback
                traceback.print_exc()
                self.events.put(("translation_prepared", (request_id, str(error))))

        threading.Thread(target=download, daemon=True).start()

    def set_translation_busy(self, busy: bool) -> None:
        """Lock setup controls and show activity while a translation model is downloaded."""
        state = "disabled" if busy else "readonly"
        for widget in (self.language, self.translate_to, self.microphone):
            widget.configure(state=state)
        for widget in self.speaker_buttons:
            widget.configure(state="disabled" if busy else "normal")
        if self.screens:
            self.screen_choice.configure(state=state)
        if busy:
            self.translation_progress.pack(anchor="w", fill="x", pady=(5, 2))
            if sys.platform != "darwin":
                self.translation_progress.start(12)
        else:
            self.translation_progress.stop()
            self.translation_progress.pack_forget()

    def refresh_start_button(self) -> None:
        enabled = self.model is not None and not self.translation_loading
        self.start_button.configure(
            state="normal" if enabled else "disabled",
            background=RED if enabled else "#d7d7d7",
            foreground="white" if enabled else "#777777")

    @staticmethod
    def load_ui_settings() -> dict:
        import configparser
        settings = configparser.ConfigParser()
        settings.read(UI_SETTINGS, encoding="utf-8")
        return dict(settings["live"]) if settings.has_section("live") else {}

    @staticmethod
    def save_ui_settings(values: dict) -> None:
        import configparser
        settings = configparser.ConfigParser()
        settings.read(UI_SETTINGS, encoding="utf-8")  # keeps [ui], the interface language
        settings["live"] = {key: value for key, value in values.items() if value is not None}
        try:
            with open(UI_SETTINGS, "w", encoding="utf-8") as out:
                settings.write(out)
        except OSError:
            pass  # only a convenience

    def chosen_settings(self) -> dict:
        microphone = self.microphone.get()
        return {"language": self.languages[self.language.current()][0] or "",
                "microphone": microphone if microphone in self.microphones else NO_MICROPHONE,
                "translate": self.targets[self.translate_to.current()][0] or "",
                "folder": self.folder_var.get().strip(),
                "screen": str(self.screen_choice.current()) if self.screens else ""}

    def change_interface(self, _event=None) -> None:
        code = list(ui_text.LANGUAGES)[self.interface.current()]
        if code == ui_text.language() or self.model is None:
            return
        ui_text.set_language(code)
        ui_text.save_language(code)
        self.save_ui_settings(self.chosen_settings())  # the new window offers the same choices
        import shortcuts
        threading.Thread(target=shortcuts.rename_existing, daemon=True).start()
        self.restart = (self.model, self.hotwords)
        self.root.destroy()

    def build_meters(self) -> ttk.Frame:
        frame = ttk.Frame(self.root)
        self.meters = {}
        meters = [("microphone", t("win.meter_mic"))]
        if self.has_computer_audio:
            meters.append(("computer", t("win.meter_computer")))
        for row, (key, title) in enumerate(meters):
            ttk.Label(frame, text=title, width=16).grid(row=row, column=0, sticky="w")
            canvas = tk.Canvas(frame, height=14, width=360, highlightthickness=0, background="#e6e6e6")
            canvas.grid(row=row, column=1, sticky="w", pady=2)
            bar = canvas.create_rectangle(0, 0, 0, 14, fill=GREEN, width=0)
            note = ttk.Label(frame, text="", style="Note.TLabel")
            note.grid(row=row, column=2, sticky="w", padx=8)
            self.meters[key] = (canvas, bar, note, [time.time()])
        self.mic_warning = tk.Label(
            frame, background="#fff3c4", foreground="#5d4300", font=(FONT, 10), justify="left",
            anchor="w", padx=10, pady=6, wraplength=820,
            text=t("win.mic_warning"))
        return frame

    def build_text(self) -> ttk.Frame:
        frame = ttk.Frame(self.root)
        self.panes = ttk.PanedWindow(frame, orient="horizontal")
        self.panes.pack(fill="both", expand=True)
        left, self.text = self.text_column(self.panes, t("win.transcript_head"))
        self.panes.add(left, weight=1)
        self.apply_text_size()
        self.text.insert("end", t("win.text_hint"), ("hint",))
        self.text.configure(state="disabled")
        self.to_end = ttk.Button(left, text=t("win.to_end"), command=self.scroll_to_end)
        self.draft_bar = tk.Label(
            frame, background="#eef2f5", foreground="#555555", font=(FONT, 11, "italic"),
            anchor="w", justify="left", padx=12, pady=8, wraplength=820)
        # Shown immediately after Stop. Final Whisper chunks and a queued translation can take
        # tens of seconds, so a small status in the title bar is too easy to miss.
        self.stopping_overlay = tk.Frame(
            frame, background="#fff3c4", highlightbackground="#d6a928",
            highlightthickness=1, padx=28, pady=22)
        tk.Label(
            self.stopping_overlay, text=t("win.stopping"), background="#fff3c4",
            foreground="#4f3900", font=(FONT, 14, "bold")).pack(pady=(0, 12))
        self.stop_stage_recorded = tk.Label(
            self.stopping_overlay, text="✓  " + t("win.stage_recorded"), background="#fff3c4",
            foreground=GREEN, font=(FONT, 11), anchor="w")
        self.stop_stage_recorded.pack(fill="x", pady=2)
        self.stop_stage_phrases = tk.Label(
            self.stopping_overlay, text="●  " + t("win.stage_phrases"), background="#fff3c4",
            foreground="#4f3900", font=(FONT, 11, "bold"), anchor="w")
        self.stop_stage_phrases.pack(fill="x", pady=2)
        self.stop_stage_translation = tk.Label(
            self.stopping_overlay, text="○  " + t("win.stage_translation"), background="#fff3c4",
            foreground=GREY, font=(FONT, 11), anchor="w")
        self.stop_stage_translation.pack(fill="x", pady=2)
        self.stopping_progress = ttk.Progressbar(
            self.stopping_overlay, mode="indeterminate", length=320)
        self.stopping_progress.pack(fill="x", pady=(12, 8))
        tk.Label(
            self.stopping_overlay, text=t("win.stopping_safe"), background="#fff3c4",
            foreground="#5d4300", font=(FONT, 9)).pack()
        return frame

    @staticmethod
    def text_column(parent, title: str | None = None) -> tuple[ttk.Frame, tk.Text]:
        column = ttk.Frame(parent)
        if title:
            ttk.Label(column, text=title, style="Column.TLabel").pack(anchor="w", padx=4, pady=(0, 5))
        # Tk on macOS inherits the system text colour even though this widget has an explicit
        # light background. In Dark Mode that produces white text on an almost white field.
        text = tk.Text(column, wrap="word", font=(FONT, 13), padx=12, pady=10, relief="flat",
                       background="#fbfbfb", foreground="#1f1f1f", insertbackground="#1f1f1f",
                       selectbackground="#b7d7f5", selectforeground="#111111", spacing3=4, height=8)
        scroll = ttk.Scrollbar(column, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        return column, text

    def add_translation_column(self, name: str) -> None:
        right, self.translation_text = self.text_column(self.panes, t("win.translation_head", language=name))
        self.translation_column = right
        self.translation_text.configure(background="#f6f8fb", state="disabled")
        self.panes.add(right, weight=1)
        self.translation_view_button.configure(text=t("win.hide_translation"))
        self.translation_view_button.pack(side="right", padx=(0, 12))
        self.apply_text_size()

    def toggle_translation_column(self) -> None:
        if self.translation_column is None:
            return
        visible = str(self.translation_column) in self.panes.panes()
        if visible:
            self.panes.forget(self.translation_column)
            self.translation_view_button.configure(text=t("win.show_translation"))
        else:
            self.panes.add(self.translation_column, weight=1)
            self.translation_view_button.configure(text=t("win.hide_translation"))

    def build_controls(self) -> ttk.Frame:
        frame = ttk.Frame(self.root)
        self.stop_button = ttk.Button(frame, text=t("win.stop"), style="Big.TButton", command=self.stop)
        self.stop_button.pack(side="left")
        if screenshots.SUPPORTED:
            self.shot_button = ttk.Button(frame, text=t("win.shot"), command=self.take_screenshot)
            self.shot_button.pack(side="left", padx=(12, 0))
            self.shot_note = ttk.Label(frame, text="", style="Note.TLabel")
            self.shot_note.pack(side="left", padx=(6, 0))
        ttk.Button(frame, text=t("win.open_folder"), command=self.open_folder).pack(side="left", padx=(12, 0))
        ttk.Button(frame, text=t("win.copy"), command=self.copy_text).pack(side="left", padx=(6, 0))
        ttk.Button(frame, text="A+", width=4, command=lambda: self.change_size(1)).pack(side="right")
        ttk.Button(frame, text="A−", width=4, command=lambda: self.change_size(-1)).pack(side="right", padx=(0, 4))
        self.translation_view_button = ttk.Button(frame, command=self.toggle_translation_column)
        return frame

    def apply_text_size(self) -> None:
        for text in (self.text, self.translation_text):
            if text is None:
                continue
            text.configure(font=(FONT, self.text_size))
            text.tag_configure("time", foreground=GREY, font=(FONT, max(8, self.text_size - 3)))
            text.tag_configure("draft", foreground="#737373", font=(FONT, self.text_size, "italic"))
            text.tag_configure("hint", foreground="#666666")
            text.tag_configure("info", foreground="#595959", font=(FONT, max(8, self.text_size - 3), "italic"))
            text.tag_configure("me", foreground="#1565c0", font=(FONT, self.text_size, "bold"))
            text.tag_configure("others", foreground="#2e7d32", font=(FONT, self.text_size, "bold"))
            text.tag_configure("shot", foreground="#1565c0", underline=True, font=(FONT, max(8, self.text_size - 2)))
            for number, colour in enumerate(VOICE_COLOURS):
                text.tag_configure(f"voice{number}", foreground=colour, font=(FONT, self.text_size, "bold"))

    def change_size(self, step: int) -> None:
        self.text_size = min(28, max(9, self.text_size + step))
        self.apply_text_size()

    # --- model ------------------------------------------------------------------------------------

    def load_model(self) -> None:
        # Its messages go to the console; redirecting stdout here would swallow everything the
        # other threads print meanwhile, since the redirect is process-wide.
        try:
            model, hotwords = live.load_whisper(self.args, lambda line: print(line, flush=True))
            self.events.put(("model", (model, hotwords, "")))
        except Exception as error:
            self.events.put(("model_failed", str(error)))

    # --- recording --------------------------------------------------------------------------------

    def start(self) -> None:
        microphone = self.microphones.get(self.microphone.get())
        speakers = [speaker for speaker, var in self.speakers if var.get()]
        if microphone is None and not speakers:
            messagebox.showwarning(t("win.nothing_title"), t("win.nothing_text"))
            return
        language = self.languages[self.language.current()][0]
        self.args.language = language
        entered_folder = self.folder_var.get().strip()
        if entered_folder:
            self.base_folder = os.path.abspath(os.path.expanduser(entered_folder))
        self.save_ui_settings(self.chosen_settings())
        folder = os.path.join(self.base_folder, time.strftime("%Y-%m-%d %H-%M"))
        try:
            self.session = live.LiveSession(
                self.model, folder, language, self.hotwords, microphone, speakers,
                on_final=lambda start, end, label, text: self.events.put(("final", (start, end, label, text))),
                on_draft=lambda label, text: self.events.put(("draft", (label, text))),
                on_levels=self.set_levels,
                on_mic_silent=lambda silent: self.events.put(("mic_silent", silent)),
                on_info=lambda message: self.events.put(("info", message)))
            self.session.start()
        except Exception as error:
            messagebox.showerror(t("win.start_failed"), str(error))
            return
        self.setup_frame.pack_forget()
        self.interface_box.pack_forget()  # the interface language is chosen before the recording
        self.text_frame.pack_forget()
        self.meters_frame.pack(fill="x", padx=14, pady=(0, 6))
        # Packed from the bottom first, so the buttons stay visible however long the text is.
        self.controls_frame.pack(side="bottom", fill="x", padx=14, pady=(0, 12))
        self.text_frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.mark_set("draft", "end-1c")
        self.text.mark_gravity("draft", "left")  # the draft is typed after it, the mark stays put
        self.text.configure(state="disabled")
        self.status.configure(text=t("win.recording"), foreground=RED)
        self.folder = folder
        target, name = self.targets[self.translate_to.current()]
        if target:
            self.add_translation_column(name)
            self.live_translator = translator.LiveTranslator(
                target, language, os.path.join(folder, f"meeting.live.{target}.txt"),
                on_result=lambda *result: self.events.put(("translated", result)),
                on_info=lambda message: self.events.put(("translation_info", message)))
            self.live_translator.start()

    def take_screenshot(self) -> None:
        """The chosen screen at this moment of the recording. If this window covers that screen,
        it steps aside for a moment so the screenshot shows the call, not this window."""
        if not self.session or self.session.stopping.is_set():
            return
        seconds = self.session.seconds
        path = screenshots.new_path(self.folder, seconds)
        open(path + ".partial", "wb").close()  # reserves the name until the PNG is written
        rect = self.screens[self.screen_choice.current()][1]
        hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
        hide = screenshots.overlaps(rect, screenshots.window_rect(hwnd))
        self.shot_button.configure(state="disabled")
        if hide:
            self.root.withdraw()
        self.root.after(350 if hide else 0, lambda: self.capture_screen(rect, path, seconds, hide))

    def capture_screen(self, rect, path: str, seconds: float, hidden: bool) -> None:
        try:
            pixels = screenshots.capture(rect)
        except Exception as error:
            pixels = None
            os.remove(path + ".partial")
            self.add_info(t("win.shot_failed", error=error))
        finally:
            if hidden:
                self.root.deiconify()
            self.shot_button.configure(state="normal")
        if pixels is None:
            return
        saver = threading.Thread(target=screenshots.save_png, args=(pixels, path), daemon=True)
        saver.start()
        self.shot_savers.append(saver)
        self.shot_count += 1
        self.shot_note.configure(text=t("win.shots_count", n=self.shot_count))
        self.pending_shots.append((seconds, path))

    def add_shot_marks(self, before: float | None) -> None:
        """The marks of the screenshots taken before `before` (all when None), as their own lines
        after the paragraph that was being said."""
        while self.pending_shots and (before is None or self.pending_shots[0][0] < before):
            seconds, path = self.pending_shots.pop(0)
            tag = f"shot{self.shot_count}_{int(seconds * 1000)}"
            self.text.tag_bind(tag, "<Button-1>", lambda _e, p=path: tool.open_path(p))
            self.text.tag_bind(tag, "<Enter>", lambda _e: self.text.configure(cursor="hand2"))
            self.text.tag_bind(tag, "<Leave>", lambda _e: self.text.configure(cursor=""))
            gap = "\n\n" if self.text.compare("draft", ">", "1.0") else ""
            self.append_final(gap, (), f"📷 {tool.format_clock(seconds)}", ("shot", tag))

    def set_levels(self, microphone: float, computer: float) -> None:
        self.levels = (max(microphone, self.levels[0] * 0.6), max(computer, self.levels[1] * 0.6))

    def stop(self) -> None:
        if not self.session or self.session.stopping.is_set():
            return  # a second click while stopping does nothing
        self.stop_button.configure(text=t("win.stopping_short"), state="disabled")
        self.status.configure(text=t("win.stopping"), foreground=GREY)
        self.stopping_overlay.place(relx=0.5, rely=0.5, anchor="center")
        self.stopping_overlay.lift()
        if self.live_translator:
            self.stop_stage_translation.pack(fill="x", pady=2, before=self.stopping_progress)
        else:
            self.stop_stage_translation.pack_forget()
        self.stopping_progress.start(12)
        self.root.update_idletasks()
        threading.Thread(target=self.finish_session, daemon=True).start()

    def finish_session(self) -> None:
        try:
            self.session.stop()
            if self.live_translator:
                self.events.put(("stopping_stage", "translation"))
                self.live_translator.finish()  # translates what is still waiting
            for saver in self.shot_savers:
                saver.join()
            if self.shot_savers:
                folder = os.path.dirname(self.session.txt_path)
                screenshots.write_markdown_for(
                    [self.session.txt_path] + [os.path.join(folder, f"meeting.live.{code}.txt")
                                               for code in translator.LANGUAGES],
                    report=lambda line: print(line, flush=True))
            self.events.put(("stopped", None))
        except Exception as error:
            import traceback
            traceback.print_exc()
            self.events.put(("stop_failed", str(error)))
        finally:
            self.session.stopping.set()

    # --- text -------------------------------------------------------------------------------------

    def at_end(self) -> bool:
        return self.text.yview()[1] >= 0.999

    def scroll_to_end(self) -> None:
        self.text.see("end")
        self.to_end.place_forget()

    # The mark "draft" sits where the final text ends; everything after it is the draft. Final
    # text is added by removing the draft, appending at the end and moving the mark there.

    def append_final(self, *chunks_and_tags) -> None:
        follow = self.at_end()
        self.text.configure(state="normal")
        self.text.delete("draft", "end-1c")
        self.text.insert("end-1c", *chunks_and_tags)
        self.text.mark_set("draft", "end-1c")
        self.text.configure(state="disabled")
        self.after_insert(follow)

    def add_final(self, start: float, end: float, label: str | None, text: str) -> None:
        new_paragraph = (self.last_end is None or label != self.last_label
                         or start - self.last_end >= PARAGRAPH_PAUSE
                         or start - self.paragraph_start >= PARAGRAPH_LONGEST)
        if self.live_translator:
            self.live_translator.add(start, label, text, new_paragraph, self.label_tag(label) if label else None)
        if new_paragraph:
            self.add_shot_marks(before=start)
            gap = "\n\n" if self.text.compare("draft", ">", "1.0") else ""
            name = (f"{label}: ", (self.label_tag(label),)) if label else ("", ())
            self.append_final(gap, (), f"[{tool.format_clock(start)}]  ", ("time",), *name, text, ())
            self.paragraph_start = start
        else:
            self.append_final(" " + text, ())
        self.last_end, self.last_label = end, label
        self.render_drafts()

    def add_translation(self, start: float, label: str | None, text: str, new_paragraph: bool, tag) -> None:
        """A translated phrase in the second column, in the paragraphs of the original."""
        widget = self.translation_text
        follow = widget.yview()[1] >= 0.999
        widget.configure(state="normal")
        if new_paragraph:
            gap = "\n\n" if widget.index("end-1c") != "1.0" else ""
            name = (f"{label}: ", (tag or "others",)) if label else ("", ())
            widget.insert("end-1c", gap, (), f"[{tool.format_clock(start)}]  ", ("time",), *name, text, ())
        else:
            widget.insert("end-1c", " " + text)
        widget.configure(state="disabled")
        if follow:
            widget.see("end")

    def add_translation_info(self, message: str) -> None:
        widget = self.translation_text
        if widget is None:
            return
        widget.configure(state="normal")
        widget.insert("end-1c", ("\n" if widget.index("end-1c") != "1.0" else "") + f"({message})\n", ("info",))
        widget.configure(state="disabled")
        widget.see("end")

    def label_tag(self, label: str) -> str:
        """Blue for you; a colour of its own for every voice of the other side ("Собеседник 2")."""
        mine = live.STREAM_LABELS.get(self.session.language or "", ("You",))[0] if self.session else ""
        if label == mine:
            return "me"
        number = label.rsplit(" ", 1)[-1]
        return f"voice{(int(number) - 1) % len(VOICE_COLOURS)}" if number.isdigit() else "others"

    def set_draft(self, label: str | None, text: str) -> None:
        self.drafts[label] = text.rstrip(" .…")
        self.render_drafts()

    def render_drafts(self) -> None:
        follow = self.at_end()
        self.text.configure(state="normal")
        self.text.delete("draft", "end-1c")
        self.text.configure(state="disabled")
        shown = [(f"{label}: " if label else "") + text for label, text in self.drafts.items() if text]
        if shown:
            self.draft_bar.configure(text=t("win.draft", text="  ·  ".join(shown)))
            if not self.draft_bar.winfo_manager():
                self.draft_bar.pack(side="bottom", fill="x", pady=(6, 0))
        else:
            self.draft_bar.pack_forget()
        self.after_insert(follow)

    def show_mic_warning(self, silent: bool) -> None:
        follow = self.at_end()
        if silent:
            self.mic_warning.grid(row=2, column=0, columnspan=3, sticky="we", pady=(4, 2))
        else:
            self.mic_warning.grid_remove()
        self.root.update_idletasks()  # the text area changes height; keep following the end
        if follow:
            self.text.see("end")

    def add_info(self, message: str) -> None:
        self.append_final(f"\n({message})\n", ("info",))
        self.render_drafts()

    def after_insert(self, follow: bool) -> None:
        if follow:
            self.text.see("end")
        else:
            self.to_end.place(relx=1.0, rely=1.0, x=-30, y=-12, anchor="se")

    def copy_text(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.text.get("1.0", "draft"))

    def open_folder(self) -> None:
        folder = getattr(self, "folder", None) or self.base_folder
        if os.path.isdir(folder):
            tool.open_path(folder)

    # --- after the meeting ------------------------------------------------------------------------

    def show_after(self) -> None:
        if self.after_frame is not None:
            return
        self.stopping_progress.stop()
        self.stopping_overlay.place_forget()
        self.meters_frame.pack_forget()
        self.interface_box.pack_forget()
        self.controls_frame.pack_forget()
        self.text_frame.pack_forget()
        seconds = self.session.seconds
        self.status.configure(text=t("win.stopped", length=tool.format_clock(seconds)), foreground=GREEN)
        self.timer.configure(text="")
        self.model = self.session.model = None
        gc.collect()

        frame = ttk.LabelFrame(self.root, text=t("win.after"), padding=12)
        self.after_frame = frame
        frame.pack(fill="x", padx=14, pady=(0, 8))
        # Close at the bottom right of the window; packed before the text so it stays visible.
        footer = ttk.Frame(self.root)
        footer.pack(side="bottom", fill="x", padx=14, pady=(0, 12))
        ttk.Button(footer, text=t("win.close"), command=self.on_close).pack(side="right")
        self.text_frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        ttk.Label(frame, text=t("win.live_saved", path=self.session.txt_path), style="Note.TLabel",
                  wraplength=760).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, text=t("win.after_intro"), wraplength=760).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(6, 10))
        ttk.Label(frame, text=t("win.section_transcript"), style="Note.TLabel").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(0, 2))

        self.redo = tk.BooleanVar(value=True)
        self.split = tk.BooleanVar(value=False)
        self.count = tk.StringVar(value="0")
        self.check = tk.BooleanVar(value=False)
        self.summary = tk.BooleanVar(value=False)
        self.delete_sound = tk.BooleanVar(value=False)
        self.redo_box = ttk.Checkbutton(frame, text=t("win.redo"), variable=self.redo, command=self.refresh_after)
        self.redo_box.grid(row=3, column=0, columnspan=3, sticky="w", pady=2)
        call = len(self.session.streams) >= 2 if hasattr(self.session, "streams") else False
        self.is_call = call  # a call has "Вы" / "Собеседники" labels even without the separation
        self.split_box = ttk.Checkbutton(
            frame, text=t("win.split_call") if call else t("win.split"), variable=self.split,
            command=self.refresh_after)
        self.split_box.grid(row=4, column=0, sticky="w", padx=(22, 0), pady=2)
        self.count_box = ttk.Spinbox(frame, from_=0, to=20, width=4, textvariable=self.count)
        self.count_box.grid(row=4, column=1, sticky="w", pady=2)
        ttk.Label(frame, text=t("win.count_note_call") if call else t("win.count_note"),
                  style="Note.TLabel").grid(row=4, column=2, sticky="w", padx=6)
        self.check_box = ttk.Checkbutton(frame, text=t("win.check"),
                                         variable=self.check, command=self.refresh_after)
        self.check_box.grid(row=5, column=0, columnspan=3, sticky="w", padx=(22, 0), pady=2)
        live_target = self.live_translator.target if self.live_translator else None
        self.translate = tk.BooleanVar(value=bool(live_target))
        self.check_translation = tk.BooleanVar(value=False)
        line = ttk.Frame(frame)
        line.grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 2))
        self.translate_box = ttk.Checkbutton(line, text=t("win.after_translate"), variable=self.translate,
                                             command=self.refresh_after)
        self.translate_box.pack(side="left")
        self.after_targets = ui_text.meeting_languages()[:3]
        self.after_target = ttk.Combobox(line, state="readonly", width=16,
                                         values=[name for _, name in self.after_targets])
        self.after_target.current(next((i for i, (code, _) in enumerate(self.after_targets)
                                        if code == live_target), 0))
        self.after_target.pack(side="left", padx=6)
        ttk.Label(line, text=t("win.translate_local"), style="Note.TLabel").pack(side="left", padx=4)
        self.check_translation_box = ttk.Checkbutton(frame, text=t("win.check_translation"),
                                                     variable=self.check_translation, command=self.refresh_after)
        self.check_translation_box.grid(row=7, column=0, columnspan=3, sticky="w", padx=(22, 0), pady=2)
        self.summary_box = ttk.Checkbutton(frame, text=t("win.summary"), variable=self.summary,
                                           command=self.refresh_after)
        self.summary_box.grid(row=8, column=0, columnspan=3, sticky="w", pady=(8, 2))

        self.ai_row = ttk.Frame(frame)
        self.ai_row.grid(row=9, column=0, columnspan=3, sticky="w", padx=(22, 0), pady=(4, 2))
        ttk.Label(self.ai_row, text=t("win.ai")).pack(side="left")
        self.ai_choice = ttk.Combobox(self.ai_row, state="disabled", width=52)
        self.ai_choice.pack(side="left", padx=6)
        self.ai_note = ttk.Label(frame, text=t("win.searching"), style="Note.TLabel", wraplength=760)
        self.ai_note.grid(row=10, column=0, columnspan=3, sticky="w", padx=(22, 0))
        self.path_row = ttk.Frame(frame)
        ttk.Label(self.path_row, text=t("win.path"), wraplength=740).pack(anchor="w")
        entry_line = ttk.Frame(self.path_row)
        entry_line.pack(anchor="w", pady=(2, 0))
        self.path_entry = ttk.Entry(entry_line, width=56)
        self.path_entry.pack(side="left")
        self.try_button = ttk.Button(entry_line, text=t("win.try_path"), command=self.try_path)
        self.try_button.pack(side="left", padx=6)
        self.ai_warning = ttk.Label(frame, foreground=RED, wraplength=760, text=t("win.ai_rules"))
        self.ai_warning.grid(row=12, column=0, columnspan=3, sticky="w", padx=(22, 0), pady=(2, 4))

        self.delete_box = ttk.Checkbutton(frame, text=t("win.delete_sound"), variable=self.delete_sound)
        self.delete_box.grid(row=13, column=0, columnspan=3, sticky="w", pady=(8, 2))
        buttons = ttk.Frame(frame)
        buttons.grid(row=14, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.run_button = tk.Button(
            buttons, text=t("win.run"), command=self.run_processing,
            font=(FONT, 12, "bold"), background=GREEN, foreground="white",
            activebackground="#245c2a", activeforeground="white", disabledforeground="#777777",
            relief="flat", borderwidth=0, padx=20, pady=8, cursor="hand2")
        self.run_button.pack(side="left")
        # Takes the place of Run while the processing runs.
        self.cancel_button = ttk.Button(buttons, text=t("win.cancel"), style="Big.TButton",
                                        command=self.cancel_processing)
        self.folder_button = ttk.Button(buttons, text=t("win.open_folder"), command=self.open_folder)
        self.folder_button.pack(side="left", padx=(12, 0))
        # The texts with screenshots (Markdown) as HTML with the pictures inside, for any browser.
        self.export_button = ttk.Button(buttons, text=t("win.export_html"), command=self.export_html)
        self.export_button.pack(side="left", padx=(6, 0))
        self.results_heading = ttk.Label(frame, text=t("win.ready_results"), style="Note.TLabel")
        self.result_buttons = ttk.Frame(frame)
        ttk.Label(frame, text=t("win.processing_estimate"), style="Note.TLabel", wraplength=760).grid(
            row=15, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.processing_panel = ttk.Frame(frame)
        ttk.Label(self.processing_panel, text=t("win.processing_visible"), font=(FONT, 10, "bold")).pack(
            anchor="w", pady=(0, 6))
        self.processing_progress = ttk.Progressbar(self.processing_panel, mode="indeterminate", length=520)
        self.processing_progress.pack(fill="x")
        self.refresh_export()
        self.refresh_after()
        threading.Thread(target=lambda: self.events.put(
            ("ai", ai_engines.verify_engines(ai_engines.find_engines()))), daemon=True).start()

    def refresh_after(self) -> None:
        if self.processing:
            return  # everything stays locked until it ends
        redo = self.redo.get()
        self.split_box.configure(state="normal" if redo else "disabled")
        self.count_box.configure(state="normal" if redo and self.split.get() else "disabled")
        can_check = redo and (self.split.get() or getattr(self, "is_call", False))
        if not can_check:
            self.check.set(False)
        self.check_box.configure(state="normal" if can_check else "disabled")
        translate = self.translate.get()
        self.after_target.configure(state="readonly" if translate else "disabled")
        if not translate:
            self.check_translation.set(False)
        self.check_translation_box.configure(state="normal" if translate else "disabled")
        needs_ai = self.check.get() or self.summary.get() or self.check_translation.get()
        for widget in (self.ai_row, self.ai_note, self.ai_warning):
            if needs_ai and (widget is not self.ai_note or widget.cget("text")):
                widget.grid()
            else:
                widget.grid_remove()
        if needs_ai and not self.found_ai and self.ai_note.cget("text") != t("win.searching"):
            self.path_row.grid(row=11, column=0, columnspan=3, sticky="w", padx=(22, 0), pady=2)
        else:
            self.path_row.grid_remove()

    def show_ai(self, found: dict, left_out: dict) -> None:
        """Only tools that are installed and logged in are offered; the others are named with
        what to do."""
        self.found_ai = found
        self.ai_keys = list(found)
        self.ai_choice.configure(values=[ai_engines.describe(e, found[e]) for e in self.ai_keys],
                                 state="readonly" if found and not self.processing else "disabled")
        notes = [t("ai.installed_but", title=ai_engines.title(e), reason=reason) for e, reason in left_out.items()]
        if found:
            self.ai_choice.current(0)
        else:
            notes.insert(0, t("win.no_ai"))
        self.ai_note.configure(text="\n".join(notes))
        self.refresh_after()

    def try_path(self) -> None:
        result = ai_engines.classify(self.path_entry.get())
        if not result:
            messagebox.showwarning(t("win.not_found_title"), t("ai.path_wrong").strip())
            return
        usable, left_out = ai_engines.verify_engines(dict([result]))
        if not usable:
            messagebox.showwarning(t("win.not_logged_title"),
                                   t("win.found_but", title=ai_engines.title(result[0]), reason=left_out[result[0]]))
            return
        ai_engines.remember(*result)
        self.show_ai(usable, {})

    def run_processing(self) -> None:
        if not (self.redo.get() or self.summary.get() or self.translate.get()):
            messagebox.showinfo(t("win.nothing_to_do_title"), t("win.nothing_to_do"))
            return
        if (self.check.get() or self.summary.get() or self.check_translation.get()) and not self.found_ai:
            if self.ai_note.cget("text") == t("win.searching"):
                messagebox.showinfo(t("win.wait_title"), t("win.wait"))
            else:
                messagebox.showwarning(t("win.no_ai_title"), t("win.no_ai_text"))
            return
        ai = self.ai_keys[self.ai_choice.current()] if self.found_ai else None
        folder = os.path.dirname(self.session.wav_path)
        if self.redo.get():
            argv = [self.session.wav_path, "--srt", "--out-dir", folder, "--force"]
            if self.args.language:
                argv += ["--language", self.args.language]
            if self.split.get():
                count = self.count.get().strip()
                argv += ["--speakers"] + ([count] if count.isdigit() and int(count) > 0 else [])
            if self.check.get():
                argv.append("--check")
        else:
            argv = [self.session.txt_path, "--force"]
        if self.summary.get():
            argv.append("--summary")
        if self.translate.get():
            argv += ["--translate", self.after_targets[self.after_target.current()][0]]
            if self.check_translation.get():
                argv.append("--check-translation")
        if ai:
            argv += ["--ai", ai]
        self.cancelled = False
        # Read here: Tk variables are not to be read from the thread that follows the processing.
        self.delete_after = self.delete_sound.get()
        self.lock_after(True)
        self.status.configure(text=t("win.processing"), foreground=GREY)
        self.text.configure(state="normal")
        self.text.insert("end", t("win.processing_head"), ("info",))
        self.text.configure(state="disabled")
        self.text.see("end")
        command = [sys.executable, os.path.join(TOOL_DIR, "transcribe.py")] + argv
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
        # Its own process group, so Stop also ends what it started (the venv's python.exe
        # launcher on Windows, an AI tool).
        extra = ({"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
                 if os.name == "nt" else {"start_new_session": True})
        try:
            self.processing = subprocess.Popen(
                command, cwd=TOOL_DIR, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1, **extra)
        except OSError as error:
            self.events.put(("log", f"FAILED: {error}"))
            self.events.put(("processed", 1))
            return
        threading.Thread(target=self.follow_processing, args=(self.processing,), daemon=True).start()

    def follow_processing(self, process: subprocess.Popen) -> None:
        for line in process.stdout:
            if line.strip():
                self.events.put(("log", line.rstrip()))
        code = process.wait()
        if code == 0 and not self.cancelled and self.delete_after and os.path.exists(self.session.wav_path):
            os.remove(self.session.wav_path)
            self.events.put(("log", t("live.sound_deleted")))
        self.events.put(("processed", code))

    def lock_after(self, locked: bool) -> None:
        """While the processing runs, its settings cannot be changed and Run becomes Stop."""
        if locked:
            for widget in (self.redo_box, self.split_box, self.count_box, self.check_box, self.summary_box,
                           self.translate_box, self.after_target, self.check_translation_box,
                           self.ai_choice, self.path_entry, self.try_button, self.delete_box):
                widget.configure(state="disabled")
            self.run_button.pack_forget()
            self.cancel_button.configure(state="normal")
            self.cancel_button.pack(side="left", before=self.folder_button)
            self.processing_panel.grid(row=16, column=0, columnspan=3, sticky="ew", pady=(12, 2))
            self.processing_progress.start(12)
        else:
            self.processing_progress.stop()
            self.processing_panel.grid_remove()
            self.cancel_button.pack_forget()
            self.run_button.pack(side="left", before=self.folder_button)
            for widget in (self.redo_box, self.summary_box, self.translate_box, self.path_entry, self.try_button,
                           self.delete_box):
                widget.configure(state="normal")
            self.ai_choice.configure(state="readonly" if self.found_ai else "disabled")
            self.refresh_after()
        self.refresh_export(locked)

    def refresh_export(self, locked: bool = False) -> None:
        folder = os.path.dirname(self.session.wav_path)
        self.export_button.configure(state="normal" if screenshots.exportable(folder) and not locked else "disabled")

    def export_html(self) -> None:
        folder = os.path.dirname(self.session.wav_path)
        self.export_button.configure(state="disabled")
        self.status.configure(text=t("win.exporting"), foreground=GREY)

        def work():
            try:
                self.events.put(("exported", screenshots.export_html(folder)))
            except Exception as error:
                self.events.put(("exported", error))

        threading.Thread(target=work, daemon=True).start()

    def show_exported(self, result) -> None:
        self.refresh_export(bool(self.processing))
        if isinstance(result, Exception):
            self.status.configure(text=t("win.export_failed", error=result), foreground=RED)
            return
        self.status.configure(text=t("win.exported", files=", ".join(os.path.basename(p) for p in result)),
                              foreground=GREEN)
        if result:
            tool.open_path(result[0])

    def cancel_processing(self) -> None:
        if not self.processing or self.processing.poll() is not None:
            return
        self.cancelled = True
        self.cancel_button.configure(state="disabled")
        self.status.configure(text=t("win.cancelling"), foreground=GREY)
        stop_process_tree(self.processing)

    def show_results(self, code: int) -> None:
        folder = os.path.dirname(self.session.wav_path)
        self.processing = None
        if self.cancelled:
            # A transcript is written to <name>.partial and renamed only when complete.
            for leftover in glob.glob(os.path.join(glob.escape(folder), "*.partial")):
                os.remove(leftover)
            self.status.configure(text=t("win.cancelled"), foreground=RED)
            self.events.put(("log", t("win.cancelled_note")))
        else:
            self.status.configure(text=t("win.done") if code == 0 else t("win.done_errors"),
                                  foreground=GREEN if code == 0 else RED)
        self.lock_after(False)
        for child in self.result_buttons.winfo_children():
            child.destroy()
        results = [("meeting.checked.md", "win.text_with_shots"), ("meeting.md", "win.text_with_shots"),
                   ("meeting.checked.txt", "win.checked_text"), ("meeting.txt", "win.text"),
                   ("meeting.live.md", "win.text_with_shots")]
        for code in translator.LANGUAGES:
            results += [(f"meeting.{code}.checked.txt", "win.checked_translation"), (f"meeting.{code}.txt", "win.translation"),
                        (f"meeting.live.{code}.checked.txt", "win.checked_translation"),
                        (f"meeting.live.{code}.txt", "win.translation")]
        results += [("meeting.summary.md", "win.summary_file"), ("meeting.live.summary.md", "win.summary_file")]
        for name, key in results:
            path = os.path.join(folder, name)
            label = t("win.open", what=t(key))
            if os.path.exists(path) and not any(b.cget("text") == label for b in self.result_buttons.winfo_children()):
                self.results_heading.grid(row=17, column=0, columnspan=3, sticky="w", pady=(14, 3))
                self.result_buttons.grid(row=18, column=0, columnspan=3, sticky="w")
                ttk.Button(self.result_buttons, text=label,
                           command=lambda p=path: tool.open_path(p)).pack(anchor="w", pady=2)

    # --- events -----------------------------------------------------------------------------------

    def poll(self) -> None:
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "model":
                    self.model, self.hotwords, note = data
                    self.status.configure(text=t("win.ready"), foreground=GREEN)
                    self.refresh_start_button()
                    self.interface.configure(state="readonly")
                    self.prepare_translation()
                elif kind == "model_failed":
                    self.status.configure(text=t("win.model_failed"), foreground=RED)
                    messagebox.showerror(t("win.error"), t("win.model_failed_text", error=data, setup=tool.SETUP_HINT))
                elif kind == "final":
                    self.add_final(*data)
                elif kind == "draft":
                    self.set_draft(*data)
                elif kind == "mic_silent":
                    self.show_mic_warning(data)
                elif kind == "info":
                    self.add_info(data)
                elif kind == "stopped":
                    self.add_shot_marks(before=None)
                    self.show_after()
                elif kind == "stopping_stage":
                    if data == "translation":
                        self.stop_stage_phrases.configure(
                            text="✓  " + t("win.stage_phrases"), foreground=GREEN, font=(FONT, 11))
                        self.stop_stage_translation.configure(
                            text="●  " + t("win.stage_translation"), foreground="#4f3900",
                            font=(FONT, 11, "bold"))
                elif kind == "stop_failed":
                    self.stopping_progress.stop()
                    self.stopping_overlay.place_forget()
                    self.status.configure(text=t("win.error"), foreground=RED)
                    messagebox.showerror(t("win.error"), t("win.stop_failed", error=data))
                elif kind == "ai":
                    self.show_ai(*data)
                elif kind == "log":
                    self.text.configure(state="normal")
                    self.text.insert("end", data + "\n", ("info",))
                    self.text.configure(state="disabled")
                    self.text.see("end")
                elif kind == "exported":
                    self.show_exported(data)
                elif kind == "translated":
                    self.add_translation(*data)
                elif kind == "translation_info":
                    self.add_translation_info(data)
                elif kind == "translation_progress":
                    request_id, downloaded = data
                    if request_id == self.translation_prepare_id:
                        done_mb = max(0, int(downloaded / (1024 * 1024)))
                        self.translation_progress.configure(value=min(done_mb, self.translation_expected_mb))
                        self.translation_note.configure(
                            text=t("win.translate_progress", done=done_mb, total=self.translation_expected_mb),
                            foreground=GREY)
                elif kind == "translation_prepared":
                    request_id, error = data
                    if request_id == self.translation_prepare_id:
                        self.translation_loading = False
                        self.translation_loading_pair = None
                        self.set_translation_busy(False)
                        self.translation_note.configure(
                            text=t("win.translate_failed", error=error) if error else t("win.translate_ready"),
                            foreground=RED if error else GREEN)
                        self.refresh_start_button()
                elif kind == "processed":
                    self.show_results(data)
        except queue.Empty:
            pass
        if self.session and not self.session.stopping.is_set():
            self.timer.configure(text=tool.format_clock(self.session.seconds))
            self.draw_meters()
        self.root.after(100, self.poll)

    def draw_meters(self) -> None:
        import math
        levels = {"microphone": self.levels[0], "computer": self.levels[1]}
        for key, (canvas, bar, note, last_heard) in self.meters.items():
            level = levels[key]
            decibels = 20 * math.log10(level) if level > 1e-6 else -90
            fraction = min(1.0, max(0.0, (decibels + 60) / 60))
            width = int(canvas.cget("width"))
            canvas.coords(bar, 0, 0, int(width * fraction), 14)
            if decibels > -45:
                last_heard[0] = time.time()
                note.configure(text="")
            elif time.time() - last_heard[0] > 15:
                note.configure(text=t("win.silence"))

    def on_close(self) -> None:
        if self.processing and self.processing.poll() is None:
            if not messagebox.askyesno(t("win.processing_title"), t("win.close_processing")):
                return
            self.cancelled = True
            stop_process_tree(self.processing)
        elif self.session and not self.session.stopping.is_set():
            if not messagebox.askyesno(t("win.recording_title"), t("win.close_question")):
                return
            self.status.configure(text=t("win.stopping_short"), foreground=GREY)
            self.root.update()
            self.session.stop()
        self.root.destroy()


def stop_process_tree(process: subprocess.Popen) -> None:
    """Ends a process and everything it started."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, timeout=30)
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        process.kill()


def set_icon(root: tk.Tk) -> None:
    """The red microphone of the live-transcribe shortcut, in the title bar and the taskbar."""
    try:
        if os.name == "nt":
            root.iconbitmap(default=os.path.join(ICONS, "live.ico"))
        else:
            root.icon_image = tk.PhotoImage(file=os.path.join(ICONS, "live.png"))
            root.iconphoto(True, root.icon_image)
    except tk.TclError:
        pass  # no icon is no reason not to start


def run(args) -> int:
    global FONT
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text on high-DPI screens
            # Its own taskbar button with its own icon, not grouped under python.exe.
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("transcribe.live")
        except Exception:
            pass
    loaded = None
    while True:  # once more for every change of the interface language
        root = tk.Tk()
        if sys.platform == "darwin":
            families = set(tkfont.families(root))
            FONT = next((name for name in ("SF Pro Text", "Helvetica Neue", "Helvetica")
                         if name in families), "TkDefaultFont")
        elif os.name != "nt":
            families = set(tkfont.families(root))
            FONT = next((name for name in LINUX_FONTS if name in families), "TkDefaultFont")
        app = App(root, args, loaded)
        root.mainloop()
        if not app.restart:
            return 0
        loaded = app.restart
