"""The application window, in the interface language (ui_text.py).

0. Home: two equal ways in, "Meeting now" and "Existing recording", and the last results.
   "Existing recording" (also the Transcribe a recording shortcut) goes straight to step 3 for
   the chosen files. Changing the interface language rebuilds the window, keeping the model.
1. Before (Meeting now, with Back): meeting language, translation, microphone and output
   devices, folder; the model loads in the background from the start.
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
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, font as tkfont, messagebox, ttk

import ai_engines
import live
import paths
import screenshots
import transcribe as tool
import translator
import ui_text
import updates
from ui_text import t

# Stored in ui.local.ini for "do not record the microphone", whatever the interface language.
NO_MICROPHONE = "<none>"
OLD_NO_MICROPHONE = "Не записывать микрофон"  # what versions before 2026-11-13 stored
# The language and microphone chosen last time are offered again (local, not in git).
UI_SETTINGS = paths.config("ui.local.ini")
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
# Offered in the file dialog of "Transcribe a recording" (anything ffmpeg reads also works).
FILE_EXTENSIONS = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".mp3", ".wav", ".m4a",
                   ".aac", ".flac", ".ogg", ".opus", ".wma", ".txt")


class App:
    def __init__(self, root: tk.Tk, args, loaded=None):
        """loaded: (model, hotwords) kept from the window this one replaces."""
        self.root, self.args = root, args
        # False closes the application; True starts a fresh recording screen and reloads the
        # model; (model, hotwords) rebuilds the window while keeping an already loaded model.
        self.restart = False
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
        self.probe = None  # sound levels on the setup screen (live.LevelProbe)
        self.folded = []  # options hidden while the processing runs and while its results show
        self.levels = (0.0, 0.0)
        self.paragraph_start = self.last_end = self.last_label = None
        self.drafts = {}  # label -> unfinished phrase
        self.found_ai = {}
        # Recordings made elsewhere, chosen to be transcribed (None: the live recording flow).
        self.files = None
        self.model_loading = False
        self.pending_update = None
        self.text_size = 13
        self.base_folder = os.path.join(live.documents_folder(), "Transcripts")
        if args.out_dir:
            self.base_folder = args.out_dir

        root.title(t("win.title"))
        set_icon(root)
        root.geometry(f"900x{min(820, max(600, root.winfo_screenheight() - 90))}")
        root.minsize(720, 520)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        style = ttk.Style()
        style.configure("Big.TButton", font=(FONT, 11, "bold"), padding=(14, 6))
        style.configure("TLabel", font=(FONT, 10))
        style.configure("TCheckbutton", font=(FONT, 10))
        style.configure("Head.TLabel", font=(FONT, 14, "bold"))
        style.configure("Column.TLabel", font=(FONT, 11, "bold"))
        style.configure("Note.TLabel", foreground=GREY, font=(FONT, 9))

        self.build_header()
        self.screen = None  # "home", "live" (its settings), then the recording and results
        self.back_bar = ttk.Frame(self.root, padding=(14, 0, 14, 4))
        ttk.Button(self.back_bar, text=t("win.back"), command=self.show_home).pack(side="left")
        self.home_frame = self.build_home()
        self.setup_frame = self.build_setup()
        self.meters_frame = self.build_meters()
        self.text_frame = self.build_text()
        self.controls_frame = self.build_controls()
        self.after_frame = None

        # Which screen a rebuilt window of this process opens (new recording, language change).
        start_screen = getattr(args, "start_screen", "home")
        args.start_screen = "home"
        if loaded:
            self.events.put(("model", (*loaded, "")))
        elif args.files:
            # Started to transcribe recordings (shortcut, Send to): the processing loads its own
            # model, so none is loaded here. Only once: a later window of this process opens
            # the home screen.
            args.files, inputs, args.inputs = False, list(args.inputs), []
            self.show_home()
            root.after(150, lambda: self.open_files(inputs or self.ask_files()))
        else:
            # Loaded meanwhile, so a meeting can start right away; dropped if a file is chosen.
            self.start_model_loading()
        if not args.files and self.screen is None:
            self.show_live_setup() if start_screen == "live" else self.show_home()
        if os.environ.get("TRANSCRIBE_CHECK_UPDATES") == "1":
            threading.Thread(target=self.check_update, args=(False,), daemon=True).start()
        root.after(100, self.poll)

    def check_update(self, manual: bool) -> None:
        version = updates.latest_release()
        self.events.put(("update", (version, manual)))

    def manual_update(self) -> None:
        self.update_button.configure(state="disabled", text=t("win.update_checking"))
        threading.Thread(target=self.check_update, args=(True,), daemon=True).start()

    def show_help(self) -> None:
        webbrowser.open("https://github.com/sbaranau/transcribe/blob/main/%D0%98%D0%9D%D0%A1%D0%A2%D0%A0%D0%A3%D0%9A%D0%A6%D0%98%D0%AF.md")

    def show_about(self) -> None:
        messagebox.showinfo(t("win.about"), t(
            "win.about_text", version=updates.current_version(), folder=paths.DATA_DIR))

    def show_update_result(self, version: str | None, manual: bool) -> None:
        if manual:
            self.update_button.configure(state="normal", text=t("win.update"))
        if version and updates.is_newer(version):
            update_key = "win.update_text_macos" if sys.platform == "darwin" else "win.update_text"
            if messagebox.askyesno(t("win.update_title"), t(update_key, version=version)):
                webbrowser.open(updates.RELEASES_URL)
        elif manual and version:
            messagebox.showinfo(t("win.update_title"), t(
                "win.update_current", version=updates.current_version()))
        elif manual:
            messagebox.showerror(t("win.update_title"), t("win.update_failed"))

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
        self.interface = ttk.Combobox(self.interface_box, state="readonly", width=10,
                                      values=list(ui_text.LANGUAGES.values()))
        self.interface.current(list(ui_text.LANGUAGES).index(ui_text.language()))
        self.interface.bind("<<ComboboxSelected>>", self.change_interface)
        self.interface.pack(side="left")
        self.timer = ttk.Label(bar, text="", font=(FONT, 14))
        self.timer.pack(side="right")
        self.status = ttk.Label(bar, text=t("win.loading"), foreground=GREY,
                                font=(FONT, 11))
        self.status.pack(side="right", padx=16)

        self.tools_frame = ttk.Frame(self.root, padding=(14, 0, 14, 8))
        self.tools_frame.pack(fill="x")
        ttk.Button(self.tools_frame, text=t("win.about"), command=self.show_about).pack(side="right")
        ttk.Button(self.tools_frame, text=t("win.help"), command=self.show_help).pack(side="right", padx=6)
        self.update_button = ttk.Button(self.tools_frame, text=t("win.update"), command=self.manual_update)
        self.update_button.pack(side="right")

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
        microphone_line = ttk.Frame(frame)
        microphone_line.grid(row=2, column=1, sticky="w", pady=3)
        self.microphone = ttk.Combobox(microphone_line, state="readonly", width=50,
                                       values=list(self.microphones) + [t("win.no_microphone")])
        self.microphone.bind("<<ComboboxSelected>>", lambda _event: self.start_probe())
        # Levels before the start, so a silent microphone is noticed before the meeting.
        self.setup_meters = {}
        last_microphone = remembered.get("microphone")
        if last_microphone in self.microphones:
            self.microphone.set(last_microphone)
        elif last_microphone in (NO_MICROPHONE, OLD_NO_MICROPHONE) or not default_microphone:
            self.microphone.set(t("win.no_microphone"))
        else:
            self.microphone.set(default_microphone.name)
        self.microphone.pack(anchor="w")
        meter_line = ttk.Frame(microphone_line)
        meter_line.pack(anchor="w", pady=(4, 0))
        self.setup_meters["microphone"] = self.setup_meter(meter_line)
        self.setup_meters["microphone"][0].pack(side="left")
        self.setup_meters["microphone"][2].pack(side="left", padx=(6, 0))

        self.speakers = []
        self.speaker_buttons = []
        if speakers:
            ttk.Label(frame, text=t("win.computer")).grid(row=3, column=0, sticky="nw", pady=3)
            box = ttk.Frame(frame)
            box.grid(row=3, column=1, sticky="w", pady=3)
            for speaker in speakers:
                var = tk.BooleanVar(value=True)
                button = ttk.Checkbutton(box, text=speaker.name, variable=var, command=self.start_probe)
                button.pack(anchor="w")
                self.speaker_buttons.append(button)
                self.speakers.append((speaker, var))
            meter_line = ttk.Frame(box)
            meter_line.pack(anchor="w", pady=(3, 0))
            self.setup_meters["computer"] = self.setup_meter(meter_line)
            self.setup_meters["computer"][0].pack(side="left")
            self.setup_meters["computer"][2].pack(side="left", padx=(6, 0))
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
        # Aqua ignores custom colours on both ttk.Button and tk.Button. A focusable label keeps
        # the primary action truly red on macOS while remaining clickable and keyboard-accessible.
        self.start_enabled = False
        self.start_button = tk.Label(
            frame, text=t("win.start"), font=(FONT, 16, "bold"), background="#d7d7d7",
            foreground="#777777", padx=28, pady=13, cursor="arrow", takefocus=True)
        self.start_button.bind("<Button-1>", lambda _event: self.start() if self.start_enabled else None)
        self.start_button.bind("<Return>", lambda _event: self.start() if self.start_enabled else None)
        self.start_button.bind("<space>", lambda _event: self.start() if self.start_enabled else None)
        self.start_button.bind("<Enter>", lambda _event: self.start_button.configure(
            background="#c51f30") if self.start_enabled else None)
        self.start_button.bind("<Leave>", lambda _event: self.start_button.configure(
            background="#e32636") if self.start_enabled else None)
        self.start_button.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(10, 2))
        return frame

    # --- home screen ------------------------------------------------------------------------------

    def build_home(self) -> ttk.Frame:
        """Two equal ways in, so neither hides behind the other: a meeting now, or a recording
        made earlier. Below them the last results, to find a transcript again."""
        frame = ttk.Frame(self.root, padding=(14, 8, 14, 10))
        cards = ttk.Frame(frame)
        cards.pack(fill="x")
        cards.columnconfigure((0, 1), weight=1, uniform="card")
        self.home_images = []
        specs = [("live", "home.live_title", "home.live_text", "home.live_button",
                  ("#e32636", "#c51f30"), self.show_live_setup),
                 ("transcribe", "home.file_title", "home.file_text", "home.file_button",
                  ("#1f6fc5", "#195ba3"), lambda: self.open_files(self.ask_files()))]
        for column, (icon, title, text, button, colours, command) in enumerate(specs):
            card = tk.Frame(cards, background="white", highlightbackground="#cfcfcf",
                            highlightthickness=1, padx=18, pady=16)
            card.grid(row=0, column=column, sticky="nsew", padx=(0, 6) if column == 0 else (6, 0))
            try:
                image = tk.PhotoImage(file=os.path.join(ICONS, icon + ".png")).subsample(4)
                self.home_images.append(image)
                tk.Label(card, image=image, background="white").pack(pady=(2, 8))
            except tk.TclError:
                pass  # no picture is no reason not to start
            tk.Label(card, text=t(title), font=(FONT, 16, "bold"), background="white",
                     foreground="#1f1f1f").pack()
            # Three lines in both cards, so their buttons stay level in every language.
            tk.Label(card, text=t(text), font=(FONT, 10), background="white", foreground=GREY,
                     wraplength=330, justify="center", height=3, anchor="n").pack(pady=(6, 12))
            primary_label(card, t(button), colours, command, size=13).pack(fill="x")
        self.recent_frame = ttk.Frame(frame)
        self.recent_frame.pack(fill="x", pady=(18, 0))
        return frame

    def refresh_recent(self) -> None:
        for child in self.recent_frame.winfo_children():
            child.destroy()
        items = load_recent()
        if not items:
            return
        ttk.Label(self.recent_frame, text=t("home.recent"), style="Note.TLabel").pack(anchor="w", pady=(0, 4))
        for item in items:
            line = ttk.Frame(self.recent_frame)
            line.pack(anchor="w", pady=1)
            link = tk.Label(line, text=item["name"], font=(FONT, 10, "underline"), foreground="#1565c0",
                            cursor="hand2")
            link.bind("<Button-1>", lambda _event, folder=item["folder"]: tool.open_path(folder))
            link.pack(side="left")
            kind = t("home.kind_live") if item.get("kind") == "live" else t("home.kind_file")
            ttk.Label(line, text=f"  {kind} · {item.get('date', '')}", style="Note.TLabel").pack(side="left")

    def show_home(self) -> None:
        self.screen = "home"
        self.stop_probe()
        for widget in (self.back_bar, self.setup_frame, self.text_frame):
            widget.pack_forget()
        self.status.configure(text="")
        self.refresh_recent()
        self.home_frame.pack(fill="both", expand=True)

    def show_live_setup(self) -> None:
        self.screen = "live"
        self.home_frame.pack_forget()
        self.back_bar.pack(fill="x")
        self.setup_frame.pack(fill="x", padx=14, pady=(0, 8))
        if self.model is None and not self.model_loading:
            self.start_model_loading()
        if self.model is not None:
            self.status.configure(text=t("win.ready"), foreground=GREEN)
        else:
            self.status.configure(text=t("win.loading"), foreground=GREY)
        self.start_probe()

    # --- recordings made elsewhere ----------------------------------------------------------------

    def ask_files(self) -> list[str]:
        patterns = " ".join("*" + extension for extension in FILE_EXTENSIONS)
        chosen = filedialog.askopenfilenames(
            parent=self.root, title=t("win.pick_title"),
            filetypes=[(t("win.media_files"), patterns), (t("win.all_files"), "*")])
        return [os.path.abspath(path) for path in chosen or ()]

    def open_files(self, files: list[str]) -> None:
        """Shows the processing panel for recordings (or .txt transcripts) made elsewhere."""
        files = [path for path in files if os.path.isfile(path)]
        if not files:
            return  # dialog cancelled: the screen behind it (home) stays
        if self.processing:
            return
        self.files = files
        self.folder = os.path.dirname(files[0])
        # The processing runs in its own process with its own model; two copies would not fit
        # on many graphics cards.
        self.model = self.hotwords = None
        gc.collect()
        if self.after_frame is not None:  # "Other files…": the panel is built again for them
            self.after_frame.destroy()
            self.after_footer.destroy()
            self.after_frame = None
        self.show_after()

    @staticmethod
    def file_base(path: str) -> str:
        """Output path without extension, as transcribe.py writes it: a transcript's results lie
        next to it, a recording's in a folder named after it."""
        if path.lower().endswith(".txt"):
            return os.path.splitext(path)[0]
        return tool.output_base(path, None)

    # --- sound levels before the start -----------------------------------------------------------

    @staticmethod
    def setup_meter(parent) -> tuple:
        """(canvas, bar, note, [time sound was last heard]); the caller places canvas and note."""
        canvas = tk.Canvas(parent, height=10, width=140, highlightthickness=0, background="#e6e6e6")
        bar = canvas.create_rectangle(0, 0, 0, 10, fill=GREEN, width=0)
        note = ttk.Label(parent, text="", style="Note.TLabel")
        return canvas, bar, note, [time.time()]

    def start_probe(self) -> None:
        """Listens to the chosen microphone and outputs while the setup screen is shown."""
        self.stop_probe()
        if self.screen != "live":
            return
        microphone = self.microphones.get(self.microphone.get())
        speakers = [speaker for speaker, var in self.speakers if var.get()]
        for canvas, bar, note, heard in self.setup_meters.values():
            canvas.coords(bar, 0, 0, 0, 10)
            note.configure(text="")
            heard[0] = time.time()
        try:
            self.probe = live.LevelProbe(microphone, speakers)
        except Exception as error:  # only a help: the recording reports device problems itself
            print(f"Sound levels not shown: {error}", flush=True)

    def stop_probe(self) -> None:
        probe, self.probe = self.probe, None
        if probe:
            probe.stop()

    def draw_setup_meters(self) -> None:
        microphone, computer = self.probe.levels()
        shown = {"microphone": (microphone, self.probe.microphone is not None),
                 "computer": (computer, bool(self.probe.computer))}
        for key, (canvas, bar, note, heard) in self.setup_meters.items():
            level, listening = shown[key]
            if draw_level(canvas, bar, level) > -45:
                heard[0] = time.time()
                note.configure(text="")
            elif not listening:
                note.configure(text="")
            elif key == "microphone" and time.time() - heard[0] > 4:
                note.configure(text=t("win.probe_mic_silent"), foreground=RED)
            elif key == "computer":
                note.configure(text=t("win.probe_computer"), foreground=GREY)

    def start_model_loading(self) -> None:
        self.model_loading = True
        threading.Thread(target=self.load_model, daemon=True).start()

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
        self.start_enabled = enabled
        self.start_button.configure(
            background="#e32636" if enabled else "#d7d7d7",
            foreground="white" if enabled else "#777777",
            cursor="hand2" if enabled else "arrow")

    @staticmethod
    def load_ui_settings(section: str = "live") -> dict:
        """[live]: the choices before a meeting; [after]: the processing chosen last time."""
        import configparser
        settings = configparser.ConfigParser()
        settings.read(UI_SETTINGS, encoding="utf-8")
        return dict(settings[section]) if settings.has_section(section) else {}

    @staticmethod
    def save_ui_settings(values: dict, section: str = "live") -> None:
        import configparser
        settings = configparser.ConfigParser()
        settings.read(UI_SETTINGS, encoding="utf-8")  # keeps the other sections
        settings[section] = {key: value for key, value in values.items() if value is not None}
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

    def chosen_processing(self) -> dict:
        """The processing options, offered again next time (the same for meetings and files)."""
        flag = lambda var: "1" if var.get() else "0"
        return {"split": flag(self.split), "count": self.count.get().strip() or "0", "check": flag(self.check),
                "translate": flag(self.translate),
                "target": self.after_targets[self.after_target.current()][0],
                "check_translation": flag(self.check_translation), "summary": flag(self.summary)}

    def change_interface(self, _event=None) -> None:
        code = list(ui_text.LANGUAGES)[self.interface.current()]
        if code == ui_text.language():
            return
        ui_text.set_language(code)
        ui_text.save_language(code)
        self.save_ui_settings(self.chosen_settings())  # the new window offers the same choices
        self.stop_probe()
        import shortcuts
        threading.Thread(target=shortcuts.rename_existing, daemon=True).start()
        # The rebuilt window opens the same screen and keeps a model already loaded.
        self.args.start_screen = "live" if self.screen == "live" else "home"
        self.restart = (self.model, self.hotwords) if self.model is not None else True
        self.root.destroy()

    def new_recording(self) -> None:
        """After a meeting: a clean recording screen; after a recording made elsewhere: the home
        screen. Without ending the application process."""
        if self.processing:
            return
        self.args.start_screen = "home" if self.files is not None else "live"
        self.restart = True
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
        self.stop_probe()  # the recording opens the same devices
        language = self.languages[self.language.current()][0]
        self.args.language = language
        entered_folder = self.folder_var.get().strip()
        if entered_folder:
            self.base_folder = os.path.abspath(os.path.expanduser(entered_folder))
        self.save_ui_settings(self.chosen_settings())
        folder = os.path.join(self.base_folder, time.strftime("%Y-%m-%d %H-%M-%S"))
        original_folder = folder
        number = 2
        while os.path.exists(folder):
            folder = f"{original_folder} ({number})"
            number += 1
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
            self.start_probe()
            return
        self.screen = "recording"
        self.back_bar.pack_forget()
        self.setup_frame.pack_forget()
        self.tools_frame.pack_forget()
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
        set_icon(self.root, recording=True)
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
        file_mode = self.files is not None
        media = [path for path in self.files if not path.lower().endswith(".txt")] if file_mode else []
        self.screen = "results"
        self.home_frame.pack_forget()
        self.back_bar.pack_forget()
        self.setup_frame.pack_forget()
        self.meters_frame.pack_forget()
        self.interface_box.pack_forget()
        self.controls_frame.pack_forget()
        self.text_frame.pack_forget()
        if file_mode:
            self.status.configure(text=t("win.files_chosen", count=len(self.files)), foreground=GREEN)
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")  # no "the meeting text will appear here"
            self.text.configure(state="disabled")
        else:
            seconds = self.session.seconds
            self.status.configure(text=t("win.stopped", length=tool.format_clock(seconds)), foreground=GREEN)
            self.model = self.session.model = None
            folder = os.path.dirname(self.session.wav_path)
            add_recent("live", os.path.basename(folder), folder)
        self.timer.configure(text="")
        gc.collect()

        frame = ttk.LabelFrame(self.root, text=t("win.files_after") if file_mode else t("win.after"),
                               padding=12)
        # Room for the options, the progress and some lines of the processing log below them.
        screen_height = self.root.winfo_screenheight()
        wanted = min(screen_height - 90, 1000)
        if self.root.winfo_height() < wanted and self.root.state() == "normal":
            top = max(0, min(self.root.winfo_y(), screen_height - wanted - 60))
            self.root.geometry(f"{max(self.root.winfo_width(), 900)}x{wanted}+{self.root.winfo_x()}+{top}")
        self.after_frame = frame
        self.tools_frame.pack(fill="x")
        set_icon(self.root, recording=False)
        if self.pending_update:
            pending, self.pending_update = self.pending_update, None
            self.root.after(100, lambda result=pending: self.show_update_result(*result))
        # Pack the footer before the large settings frame. Tk allocates packed widgets in packing
        # order, so primary actions remain visible even at the minimum window height.
        footer = ttk.Frame(self.root)
        self.after_footer = footer
        footer.pack(side="bottom", fill="x", padx=14, pady=(0, 12))
        ttk.Button(footer, text=t("win.close"), command=self.on_close).pack(side="right")
        self.new_recording_button = ttk.Button(
            footer, text=t("win.back_to_start") if file_mode else t("win.new_recording"),
            command=self.new_recording)
        self.new_recording_button.pack(side="right", padx=(0, 8))
        frame.pack(fill="x", padx=14, pady=(0, 8))
        # The processing log, under "Details": shown on request and when something failed.
        self.log_frame, self.log_text = self.text_column(self.root)
        self.log_text.configure(font=(FONT, 9), foreground="#444444", height=10, state="disabled")
        if not file_mode:  # the meeting's own text; a recording from elsewhere has none to show
            self.text_frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        if file_mode:
            line = ttk.Frame(frame)
            line.grid(row=0, column=0, columnspan=3, sticky="ew")
            shown = [os.path.basename(path) for path in self.files[:5]]
            if len(self.files) > 5:
                shown.append(f"… (+{len(self.files) - 5})")
            ttk.Label(line, text="\n".join(shown), font=(FONT, 10, "bold"), wraplength=600,
                      justify="left").pack(side="left", anchor="w")
            self.change_files_button = ttk.Button(
                line, text=t("win.change_files"), command=lambda: self.open_files(self.ask_files()))
            self.change_files_button.pack(side="right", anchor="n")
        else:
            ttk.Label(frame, text=t("win.live_saved", path=self.session.txt_path), style="Note.TLabel",
                      wraplength=760).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, text=t("win.files_intro") if file_mode else t("win.after_intro"),
                  wraplength=760).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 10))
        ttk.Label(frame, text=t("win.section_transcript"), style="Note.TLabel").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(0, 2))

        # The processing chosen last time is offered again; the AI steps once an AI is found.
        last = self.load_ui_settings("after")
        self.wanted_ai = {key: last.get(key) == "1" for key in ("check", "check_translation", "summary")}
        self.redo = tk.BooleanVar(value=bool(media) if file_mode else True)
        self.split = tk.BooleanVar(value=last.get("split") == "1")
        self.count = tk.StringVar(value=last.get("count", "0") if last.get("count", "0").isdigit() else "0")
        self.check = tk.BooleanVar(value=False)
        self.summary = tk.BooleanVar(value=False)
        self.delete_sound = tk.BooleanVar(value=False)
        self.redo_box = ttk.Checkbutton(frame, text=t("win.redo"), variable=self.redo, command=self.refresh_after)
        self.file_language = None
        if not file_mode:
            self.redo_box.grid(row=3, column=0, columnspan=3, sticky="w", pady=2)
        elif media:
            # A recording is always transcribed; only its language is asked (as at the start).
            line = ttk.Frame(frame)
            line.grid(row=3, column=0, columnspan=3, sticky="w", pady=2)
            ttk.Label(line, text=t("win.file_language")).pack(side="left")
            self.file_language = ttk.Combobox(line, state="readonly", width=34,
                                              values=[name for _, name in self.languages])
            # Detected by default: the language of the last live meeting says nothing about a
            # recording from elsewhere, and a wrong one makes Whisper translate instead.
            self.file_language.current(0)
            self.file_language.pack(side="left", padx=6)
        else:
            ttk.Label(frame, text=t("win.transcripts_only"), style="Note.TLabel", wraplength=760).grid(
                row=3, column=0, columnspan=3, sticky="w", pady=2)
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
        # A meeting translated while it ran is translated again from the better transcript.
        self.translate = tk.BooleanVar(value=bool(live_target) or last.get("translate") == "1")
        live_target = live_target or last.get("target")
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
        if sys.platform == "darwin":
            ttk.Button(entry_line, text=t("win.install_ai"), command=self.show_ai_install).pack(
                side="left", padx=(2, 0))
        self.ai_warning = ttk.Label(frame, foreground=RED, wraplength=760, text=t("win.ai_rules"))
        self.ai_warning.grid(row=12, column=0, columnspan=3, sticky="w", padx=(22, 0), pady=(2, 4))
        # Without any usable AI its options are hidden; this says what to install instead.
        self.ai_state = "searching"  # then "ready" or "none"
        self.no_ai_panel = tk.Frame(frame, background="#fff3c4", padx=10, pady=8)
        tk.Label(self.no_ai_panel, text=t("win.no_ai_install"), background="#fff3c4", foreground="#5d4300",
                 font=(FONT, 10), justify="left", anchor="w", wraplength=740).pack(anchor="w", fill="x")
        self.no_ai_reasons = tk.Label(self.no_ai_panel, background="#fff3c4", foreground="#5d4300",
                                      font=(FONT, 9), justify="left", anchor="w", wraplength=740)
        self.search_again_button = ttk.Button(self.no_ai_panel, text=t("win.search_again"),
                                              command=self.search_ai)
        self.search_again_button.pack(anchor="w", pady=(6, 0), side="bottom")

        self.delete_box = ttk.Checkbutton(frame, text=t("win.delete_sound"), variable=self.delete_sound)
        if not file_mode:  # someone else's recording is never deleted from here
            self.delete_box.grid(row=13, column=0, columnspan=3, sticky="w", pady=(8, 2))
        buttons = ttk.Frame(frame)
        buttons.grid(row=14, column=0, columnspan=3, sticky="w", pady=(10, 0))
        # Aqua ignores custom colours on tk.Button, making this primary action look like a faint
        # secondary control. A focusable label preserves the intended contrast on macOS.
        self.run_button = tk.Label(
            buttons, text=t("win.run"), font=(FONT, 13, "bold"),
            background="#168447", foreground="white", padx=24, pady=10,
            cursor="hand2", takefocus=True)
        self.run_button.bind("<Button-1>", lambda _event: self.run_processing())
        self.run_button.bind("<Return>", lambda _event: self.run_processing())
        self.run_button.bind("<space>", lambda _event: self.run_processing())
        self.run_button.bind("<Enter>", lambda _event: self.run_button.configure(background="#106a38"))
        self.run_button.bind("<Leave>", lambda _event: self.run_button.configure(background="#168447"))
        self.run_button.pack(side="left")
        # Takes the place of Run while the processing runs.
        self.cancel_button = ttk.Button(buttons, text=t("win.cancel"), style="Big.TButton",
                                        command=self.cancel_processing)
        self.folder_button = ttk.Button(buttons, text=t("win.open_folder"), command=self.open_folder)
        self.folder_button.pack(side="left", padx=(12, 0))
        # The texts with screenshots (Markdown) as HTML with the pictures inside, for any browser.
        self.export_button = ttk.Button(buttons, text=t("win.export_html"), command=self.export_html)
        if not file_mode:  # screenshots exist only for recordings made here
            self.export_button.pack(side="left", padx=(6, 0))
        ttk.Label(frame, text=t("win.processing_estimate"), style="Note.TLabel", wraplength=760).grid(
            row=15, column=0, columnspan=3, sticky="w", pady=(6, 0))
        # While it runs: the chosen steps with their state, instead of the raw log.
        self.processing_panel = ttk.Frame(frame)
        ttk.Label(self.processing_panel, text=t("win.processing_visible"), font=(FONT, 10, "bold")).pack(
            anchor="w", pady=(0, 4))
        self.step_file = ttk.Label(self.processing_panel, text="", style="Note.TLabel")
        self.steps_box = ttk.Frame(self.processing_panel)
        self.steps_box.pack(anchor="w", fill="x", pady=(2, 6))
        self.processing_progress = ttk.Progressbar(self.processing_panel, mode="indeterminate", length=520)
        self.processing_progress.pack(fill="x")
        line = ttk.Frame(self.processing_panel)
        line.pack(fill="x", pady=(4, 0))
        self.step_eta = ttk.Label(line, text="", style="Note.TLabel")
        self.step_eta.pack(side="left")
        self.details_buttons = [ttk.Button(line, text=t("win.details_show"), command=self.toggle_details)]
        self.details_buttons[0].pack(side="right")
        # When it is done: the results first, with the main text as the primary action.
        frame.columnconfigure(2, weight=1)  # the results panel spans the whole width
        self.done_panel = tk.Frame(frame, background="#eef7f0", highlightbackground="#9cc9a8",
                                   highlightthickness=1, padx=14, pady=12)
        self.steps = []
        self.refresh_export()
        self.search_ai()

    def search_ai(self) -> None:
        """Looks for installed and logged-in AIs in the background (also "Search again")."""
        self.ai_state = "searching"
        self.ai_note.configure(text=t("win.searching"))
        self.search_again_button.configure(state="disabled")
        self.refresh_after()
        threading.Thread(target=lambda: self.events.put(
            ("ai", ai_engines.verify_engines(ai_engines.find_engines()))), daemon=True).start()

    def refresh_after(self) -> None:
        if self.processing or self.folded:
            return  # locked until it ends; folded while the results are shown
        redo = self.redo.get()
        self.split_box.configure(state="normal" if redo else "disabled")
        self.count_box.configure(state="normal" if redo and self.split.get() else "disabled")
        # The AI options are usable only with an AI ready; while it is looked for they wait greyed
        # out, and when there is none they are not offered at all (no_ai_panel says what to do).
        ai_ready = self.ai_state == "ready"
        can_check = redo and (self.split.get() or getattr(self, "is_call", False))
        if not (can_check and ai_ready):
            self.check.set(False)
        self.check_box.configure(state="normal" if can_check and ai_ready else "disabled")
        translate = self.translate.get()
        self.after_target.configure(state="readonly" if translate else "disabled")
        if not (translate and ai_ready):
            self.check_translation.set(False)
        self.check_translation_box.configure(state="normal" if translate and ai_ready else "disabled")
        if not ai_ready:
            self.summary.set(False)
        self.summary_box.configure(state="normal" if ai_ready else "disabled")
        for box in (self.check_box, self.check_translation_box, self.summary_box):
            box.grid_remove() if self.ai_state == "none" else box.grid()
        if self.ai_state == "none":
            self.no_ai_panel.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(8, 2))
        else:
            self.no_ai_panel.grid_remove()
        needs_ai = self.check.get() or self.summary.get() or self.check_translation.get()
        searching = self.ai_state == "searching"
        for widget in (self.ai_row, self.ai_warning):
            widget.grid() if needs_ai else widget.grid_remove()
        # "Looking for AIs..." while searching; afterwards the notes (installed, not logged in).
        if searching or (needs_ai and self.ai_note.cget("text")):
            self.ai_note.grid()
        else:
            self.ai_note.grid_remove()
        if self.ai_state == "none":
            self.path_row.grid(row=11, column=0, columnspan=3, sticky="w", padx=(10, 0), pady=(2, 4))
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
        self.ai_state = "ready" if found else "none"
        self.search_again_button.configure(state="normal")
        if found:
            self.ai_choice.current(0)
            self.ai_note.configure(text="\n".join(notes))
            if self.wanted_ai:  # the AI steps chosen last time, once there is an AI for them
                self.check.set(self.wanted_ai["check"])
                self.check_translation.set(self.wanted_ai["check_translation"])
                self.summary.set(self.wanted_ai["summary"])
                self.wanted_ai = None
        else:
            # Installed but not logged in, for example: said in the panel, where it helps.
            self.ai_note.configure(text="")
            self.no_ai_reasons.configure(text="\n".join(notes))
            if notes:
                self.no_ai_reasons.pack(anchor="w", fill="x", pady=(6, 0))
            else:
                self.no_ai_reasons.pack_forget()
        self.refresh_after()

    def try_path(self) -> None:
        if not self.path_entry.get().strip():
            usable, left_out = ai_engines.verify_engines(ai_engines.find_engines())
            self.show_ai(usable, left_out)
            if not usable:
                messagebox.showwarning(t("win.not_found_title"), t("ai.path_wrong").strip())
            return
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

    def show_ai_install(self) -> None:
        """Show copyable, beginner-friendly installation steps for the packaged macOS app."""
        dialog = tk.Toplevel(self.root)
        dialog.title(t("win.install_ai_title"))
        dialog.geometry("760x610")
        dialog.minsize(620, 460)
        dialog.transient(self.root)
        ttk.Label(dialog, text=t("win.install_ai_title"), font=(FONT, 16, "bold")).pack(
            anchor="w", padx=22, pady=(20, 6))
        ttk.Label(dialog, text=t("win.install_ai_copy"), wraplength=710, justify="left").pack(
            anchor="w", padx=22, pady=(0, 10))
        instructions = """CODEX CLI (ChatGPT)

1. Install Codex for the current user (no administrator password or Homebrew needed):
curl -fsSL https://chatgpt.com/codex/install.sh | sh

2. Add the user programs folder to PATH:
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zprofile
export PATH="$HOME/.local/bin:$PATH"

3. Log in and check:
codex login
codex login status


CLAUDE CODE

1. Install Claude Code:
curl -fsSL https://claude.ai/install.sh | bash

2. Add it to PATH:
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zprofile
export PATH="$HOME/.local/bin:$PATH"

3. Start Claude, select your account type and complete login in the browser:
claude

After installation, paste this into the Path field if automatic detection still fails:
Codex: ~/.local/bin/codex
Claude: ~/.local/bin/claude
"""
        text = tk.Text(dialog, wrap="word", font=("Menlo", 11), padx=12, pady=12)
        text.insert("1.0", instructions)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, padx=22, pady=(0, 12))
        ttk.Button(dialog, text=t("win.close"), command=dialog.destroy).pack(pady=(0, 18))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.grab_set()

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
        if self.files is not None:
            # Results in a folder named after each recording, next to it (transcribe.py's default).
            argv = list(self.files) + ["--force"]
            if self.redo.get():
                argv.append("--srt")
                language = self.languages[self.file_language.current()][0] if self.file_language else None
                if language:
                    argv += ["--language", language]
                if self.split.get():
                    count = self.count.get().strip()
                    argv += ["--speakers"] + ([count] if count.isdigit() and int(count) > 0 else [])
                if self.check.get():
                    argv.append("--check")
        elif self.redo.get():
            folder = os.path.dirname(self.session.wav_path)
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
        self.save_ui_settings(self.chosen_processing(), section="after")
        self.build_steps()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.processing_started = time.time()
        self.lock_after(True)
        self.status.configure(text=t("win.processing"), foreground=GREY)
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

    # --- progress as steps ----------------------------------------------------------------------

    # Lines of transcribe.py (English for everyone) that start, end or fail a step.
    STEP_LINES = [
        ("Separating voices", "speakers", "active"), ("Waiting for the voice separation", "speakers", "active"),
        ("Speakers:", "speakers", "done"),
        ("Transcript done in", "transcribe", "done"), ("Transcript exists, kept", "transcribe", "done"),
        ("FAILED:", "transcribe", "failed"),
        ("Checking the text with", "check", "active"), ("Check done", "check", "done"),
        ("Checked text exists", "check", "done"), ("No speaker labels", "check", "skipped"),
        ("Check FAILED", "check", "failed"),
        ("Translating ", "translate", "active"), ("Translation done", "translate", "done"),
        ("Translation exists", "translate", "done"), ("Translation skipped", "translate", "skipped"),
        ("Translation FAILED", "translate", "failed"),
        ("Checking the translation with", "check_translation", "active"),
        ("Translation check done", "check_translation", "done"),
        ("Checked translation exists", "check_translation", "done"),
        ("Summary with", "summary", "active"), ("Summary done", "summary", "done"),
        ("Summary exists", "summary", "done"), ("Summary FAILED", "summary", "failed"),
    ]
    STEP_MARKS = {"pending": ("○", GREY, False), "active": ("●", "#1f1f1f", True), "done": ("✓", GREEN, False),
                  "skipped": ("–", GREY, False), "failed": ("✗", RED, True)}

    def build_steps(self) -> None:
        """The steps this run will take, from the chosen options."""
        for child in self.steps_box.winfo_children():
            child.destroy()
        wanted = []
        if self.redo.get():
            wanted.append(("transcribe", t("step.transcribe")))
            if self.split.get():
                wanted.append(("speakers", t("step.speakers")))
            if self.check.get():
                wanted.append(("check", t("step.check")))
        if self.translate.get():
            wanted.append(("translate", t("step.translate", language=self.after_target.get())))
            if self.check_translation.get():
                wanted.append(("check_translation", t("step.check_translation")))
        if self.summary.get():
            wanted.append(("summary", t("step.summary")))
        self.steps = []
        for key, title in wanted:
            row = ttk.Frame(self.steps_box)
            row.pack(anchor="w", fill="x")
            mark = tk.Label(row, width=2, font=(FONT, 11), anchor="w")
            mark.pack(side="left")
            name = tk.Label(row, text=title, font=(FONT, 10), anchor="w")
            name.pack(side="left")
            detail = tk.Label(row, text="", font=(FONT, 9), foreground=GREY, anchor="w")
            detail.pack(side="left", padx=(8, 0))
            self.steps.append({"key": key, "state": "pending", "mark": mark, "name": name, "detail": detail})
        self.step_failed = False
        self.step_file.configure(text="")
        self.step_file.pack_forget()
        self.step_eta.configure(text="")
        self.reset_steps()
        if self.steps:
            self.set_step(self.steps[0]["key"], "active")

    def reset_steps(self) -> None:
        for step in self.steps:
            self.set_step(step["key"], "pending")
            step["detail"].configure(text="")

    def set_step(self, key: str, state: str, detail: str | None = None) -> None:
        step = next((step for step in self.steps if step["key"] == key), None)
        if step is None:
            return
        if state == "active" and step["state"] in ("done", "failed", "skipped"):
            return  # e.g. "Waiting for the voice separation" after it already finished
        step["state"] = state
        symbol, colour, bold = self.STEP_MARKS[state]
        step["mark"].configure(text=symbol, foreground=colour)
        step["name"].configure(foreground="#1f1f1f" if state != "pending" else GREY,
                               font=(FONT, 10, "bold") if bold else (FONT, 10))
        if detail is not None:
            step["detail"].configure(text=detail)
        if state == "failed":
            self.step_failed = True
        if state != "active" and key == "transcribe":
            self.processing_progress.configure(mode="indeterminate")
            self.processing_progress.start(12)
            self.step_eta.configure(text="")
        if state in ("done", "skipped"):
            # The next step that has not started yet is what runs now.
            later = [s for s in self.steps if s["state"] == "pending"]
            if later and not any(s["state"] == "active" for s in self.steps):
                self.set_step(later[0]["key"], "active")

    def follow_step(self, line: str) -> None:
        """Moves the steps on from one line of the processing log."""
        import re
        text = line.strip()
        number = re.match(r"\[(\d+)/(\d+)\] (.+)", text)
        if number or (len(self.files or []) > 1 and text in self.files):
            # The next recording (or transcript) of several: its steps start again.
            self.processing_progress.configure(mode="indeterminate")
            self.processing_progress.start(12)
            self.reset_steps()
            path = number.group(3) if number else text
            index = self.files.index(path) + 1 if path in (self.files or []) else int(number.group(1))
            self.step_file.configure(text=t("step.file", n=index, total=len(self.files or [path]),
                                            name=os.path.basename(path)))
            if self.files and len(self.files) > 1:
                self.step_file.pack(anchor="w", before=self.steps_box)
            if self.steps:
                if number:
                    self.set_step(self.steps[0]["key"], "active")
                else:  # a transcript is not transcribed again
                    self.set_step("transcribe", "skipped")
                    later = [s for s in self.steps if s["state"] == "pending"]
                    if later and not any(s["state"] == "active" for s in self.steps):
                        self.set_step(later[0]["key"], "active")
            return
        progress = re.search(r" / \S+ \((\d+)%\), elapsed (\S+)", text)
        if progress and not text.startswith("voices"):
            percent = int(progress.group(1))
            self.set_step("transcribe", "active", f"{percent}%")
            self.processing_progress.stop()
            self.processing_progress.configure(mode="determinate", maximum=100, value=percent)
            elapsed = clock_seconds(progress.group(2))
            if 3 <= percent < 100 and elapsed:
                left = elapsed * (100 - percent) / percent
                self.step_eta.configure(text=t("step.left", time=about_minutes(left)))
            return
        voices = re.match(r"voices (\d+)%", text)
        if voices:
            self.set_step("speakers", "active", f"{voices.group(1)}%")
            return
        part = re.match(r"checking part (\d+/\d+)", text)
        if part:
            active = next((s["key"] for s in self.steps if s["state"] == "active" and s["key"] != "speakers"), None)
            if active:
                self.set_step(active, "active", part.group(1))
            return
        if text.startswith(("GPU not usable", "GPU run failed")):
            self.set_step("transcribe", "active", t("step.on_cpu"))
            return
        for start, key, state in self.STEP_LINES:
            if text.startswith(start):
                if key == "speakers" and state == "active":
                    self.set_step(key, state, "")
                else:
                    self.set_step(key, state, t("step.skipped") if state == "skipped" else None)
                if state == "active" and key != "speakers":  # the voices run alongside the transcription
                    # A step that starts ends the previous one, which said nothing more.
                    for step in self.steps:
                        if step["state"] == "active" and step["key"] not in (key, "speakers"):
                            self.set_step(step["key"], "done")
                return

    def toggle_details(self, show: bool | None = None) -> None:
        visible = bool(self.log_frame.winfo_manager())
        show = not visible if show is None else show
        if show and not visible:
            if self.text_frame.winfo_manager():
                self.log_frame.pack(fill="both", expand=True, padx=14, pady=(0, 8), before=self.text_frame)
            else:
                self.log_frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))
            self.log_text.see("end")
        elif not show and visible:
            self.log_frame.pack_forget()
        for button in self.details_buttons:
            if button.winfo_exists():
                button.configure(text=t("win.details_hide") if show else t("win.details_show"))

    def add_log(self, line: str) -> None:
        follow = self.log_text.yview()[1] >= 0.999
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.configure(state="disabled")
        if follow:
            self.log_text.see("end")
        if self.processing is not None:
            self.follow_step(line)

    def follow_processing(self, process: subprocess.Popen) -> None:
        for line in process.stdout:
            if line.strip():
                self.events.put(("log", line.rstrip()))
        code = process.wait()
        if (code == 0 and not self.cancelled and self.delete_after and self.session is not None
                and os.path.exists(self.session.wav_path)):
            os.remove(self.session.wav_path)
            self.events.put(("log", t("live.sound_deleted")))
        self.events.put(("processed", code))

    def lock_after(self, locked: bool) -> None:
        """While the processing runs, its settings cannot be changed and Run becomes Stop."""
        if locked:
            self.new_recording_button.configure(state="disabled")
            for widget in (self.redo_box, self.split_box, self.count_box, self.check_box, self.summary_box,
                           self.translate_box, self.after_target, self.check_translation_box,
                           self.ai_choice, self.path_entry, self.try_button, self.delete_box):
                widget.configure(state="disabled")
            self.search_again_button.configure(state="disabled")
            if self.files is not None:
                self.change_files_button.configure(state="disabled")
                if self.file_language:
                    self.file_language.configure(state="disabled")
            self.run_button.pack_forget()
            self.cancel_button.configure(state="normal")
            self.cancel_button.pack(side="left", before=self.folder_button)
            # The locked options are folded away, so the steps get the room; only the file line
            # (row 0), the buttons (14) and the progress (16) stay.
            self.done_panel.grid_remove()
            self.fold_options(True, keep=(0, 14, 16))
            self.processing_panel.grid(row=16, column=0, columnspan=3, sticky="ew", pady=(12, 2))
            self.processing_progress.configure(mode="indeterminate")
            self.processing_progress.start(12)
        else:
            self.new_recording_button.configure(state="normal")
            self.processing_progress.stop()
            self.processing_panel.grid_remove()
            self.cancel_button.pack_forget()
            self.run_button.pack(side="left", before=self.folder_button)
            for widget in (self.redo_box, self.summary_box, self.translate_box, self.path_entry, self.try_button,
                           self.delete_box):
                widget.configure(state="normal")
            self.ai_choice.configure(state="readonly" if self.found_ai else "disabled")
            if self.ai_state != "searching":
                self.search_again_button.configure(state="normal")
            if self.files is not None:
                self.change_files_button.configure(state="normal")
                if self.file_language:
                    self.file_language.configure(state="readonly")
        self.refresh_export(locked)

    def fold_options(self, fold: bool, keep: tuple = ()) -> None:
        """Hides the rows of the options panel except those in keep, or shows them again."""
        if fold:
            hidden = [widget for widget in self.after_frame.grid_slaves()
                      if int(widget.grid_info()["row"]) not in keep]
            for widget in hidden:
                widget.grid_remove()
            self.folded += hidden
        else:
            folded, self.folded = self.folded, []
            for widget in folded:
                widget.grid()
            self.refresh_after()  # hides again what the choices do not need

    def refresh_export(self, locked: bool = False) -> None:
        if self.session is None:
            return  # no screenshots without a recording made here
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
        if self.files is not None:
            folders = list(dict.fromkeys(os.path.dirname(self.file_base(path)) for path in self.files))
        else:
            folders = [os.path.dirname(self.session.wav_path)]
        self.processing = None
        self.lock_after(False)
        if self.cancelled:
            # A transcript is written to <name>.partial and renamed only when complete.
            for folder in folders:
                for leftover in glob.glob(os.path.join(glob.escape(folder), "*.partial")):
                    os.remove(leftover)
            self.status.configure(text=t("win.cancelled"), foreground=RED)
            self.events.put(("log", t("win.cancelled_note")))
            self.fold_options(False)
            return
        failed = code != 0 or self.step_failed
        self.status.configure(text="⚠  " + t("win.done_errors") if failed else "✓  " + t("win.done"),
                              foreground=RED if failed else GREEN)
        groups = self.result_files()
        if self.files is not None:
            for path, (_, results) in zip(self.files, groups):
                if results:
                    add_recent("file", os.path.basename(path), os.path.dirname(self.file_base(path)))
            first_folder = os.path.dirname(self.file_base(self.files[0]))
            if os.path.isdir(first_folder):
                self.folder = first_folder
        self.show_done(failed, groups)
        if self.files is not None:
            name = os.path.basename(self.files[0]) + (f" (+{len(self.files) - 1})" if len(self.files) > 1 else "")
        else:
            name = os.path.basename(folders[0])
        main = next((results[0][1] for _, results in groups if results), None)
        notify(self.root, t("win.title"), t("win.notify_errors" if failed else "win.notify_done", name=name),
               main or self.folder)

    def result_files(self) -> list:
        """[(recording name or None, [(label key, path), ...])], the main text first."""
        if self.files is None:
            folder = os.path.dirname(self.session.wav_path)
            names = [("meeting.checked.md", "win.text_with_shots"), ("meeting.md", "win.text_with_shots"),
                     ("meeting.checked.txt", "win.checked_text"), ("meeting.txt", "win.text"),
                     ("meeting.live.md", "win.text_with_shots")]
            for code in translator.LANGUAGES:
                names += [(f"meeting.{code}.checked.txt", "win.checked_translation"),
                          (f"meeting.{code}.txt", "win.translation"),
                          (f"meeting.live.{code}.checked.txt", "win.checked_translation"),
                          (f"meeting.live.{code}.txt", "win.translation")]
            names += [("meeting.summary.md", "win.summary_file"), ("meeting.live.summary.md", "win.summary_file")]
            found, shown = [], []
            for name, key in names:
                path = os.path.join(folder, name)
                # One button per kind: the best one (checked before plain, after before live).
                if os.path.exists(path) and key not in shown:
                    shown.append(key)
                    found.append((key, path))
            return [(None, found)]
        suffixes = [(".checked.txt", "win.checked_text"), (".txt", "win.text")]
        for code in translator.LANGUAGES:
            suffixes += [(f".{code}.checked.txt", "win.checked_translation"), (f".{code}.txt", "win.translation")]
        suffixes.append((".summary.md", "win.summary_file"))
        groups = []
        for path in self.files:
            base = self.file_base(path)
            found, shown = [], []
            for suffix, key in suffixes:
                result = base + suffix
                # A .txt input is the transcript itself, not a result of this run.
                if (os.path.normcase(result) == os.path.normcase(path) or not os.path.isfile(result)
                        or key in shown):
                    continue
                shown.append(key)
                found.append((key, result))
            groups.append((os.path.basename(path), found))
        return groups

    def show_done(self, failed: bool, groups) -> None:
        """The results first: the main text as the primary action, the others beside it, then the
        details and a way back to the settings."""
        panel = self.done_panel
        for child in panel.winfo_children():
            child.destroy()
        background = "#fdecea" if failed else "#eef7f0"
        panel.configure(background=background, highlightbackground="#e3a6a0" if failed else "#9cc9a8")
        took = about_minutes(time.time() - self.processing_started)
        title = ("⚠  " + t("win.done_with_errors")) if failed else ("✓  " + t("win.done_in", time=took))
        tk.Label(panel, text=title, font=(FONT, 13, "bold"), foreground=RED if failed else GREEN,
                 background=background, anchor="w").pack(fill="x")
        several = len(groups) > 1
        for name, results in groups:
            if several:
                tk.Label(panel, text=name, font=(FONT, 10, "bold"), background=background,
                         anchor="w").pack(fill="x", pady=(10, 2))
            line = tk.Frame(panel, background=background)
            line.pack(anchor="w", pady=(0 if several else 10, 0))
            for number, (key, path) in enumerate(results):
                label = t("win.open", what=t(key))
                if number == 0 and not several:
                    primary_label(line, label, ("#168447", "#106a38"),
                                  lambda p=path: tool.open_path(p), size=12).pack(side="left", padx=(0, 8))
                else:
                    ttk.Button(line, text=label, command=lambda p=path: tool.open_path(p)).pack(
                        side="left", padx=(0, 6))
            if not results:
                tk.Label(line, text=t("win.no_results"), font=(FONT, 10), background=background).pack(side="left")
        line = tk.Frame(panel, background=background)
        line.pack(fill="x", pady=(12, 0))
        ttk.Button(line, text=t("win.open_folder"), command=self.open_folder).pack(side="left")
        if self.files is None and screenshots.exportable(os.path.dirname(self.session.wav_path)):
            ttk.Button(line, text=t("win.export_html"), command=self.export_html).pack(side="left", padx=(6, 0))
        details = ttk.Button(line, text=t("win.details_show"), command=self.toggle_details)
        details.pack(side="right")
        again = tk.Label(line, text=t("win.run_again"), font=(FONT, 10, "underline"), foreground="#1565c0",
                         background=background, cursor="hand2", takefocus=True)
        for sequence in ("<Button-1>", "<Return>", "<space>"):
            again.bind(sequence, lambda _event: self.run_again())
        again.pack(side="right", padx=(0, 12))
        self.details_buttons = [self.details_buttons[0], details]
        self.fold_options(True, keep=(0,))
        panel.grid(row=17, column=0, columnspan=3, sticky="ew", pady=(10, 2))
        self.toggle_details(failed)

    def run_again(self) -> None:
        """Back from the results to the options, to run again with other choices."""
        self.done_panel.grid_remove()
        self.toggle_details(False)
        self.fold_options(False)


    # --- events -----------------------------------------------------------------------------------

    def poll(self) -> None:
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "model":
                    self.model_loading = False
                    if self.files is not None:
                        continue  # a recording was chosen meanwhile; its processing loads its own
                    self.model, self.hotwords, note = data
                    if self.screen == "live":  # the home screen has no use for it
                        self.status.configure(text=t("win.ready"), foreground=GREEN)
                    self.refresh_start_button()
                    self.interface.configure(state="readonly")
                    self.prepare_translation()
                elif kind == "model_failed":
                    self.model_loading = False
                    if self.files is not None:
                        continue
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
                    self.add_log(data)
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
                elif kind == "update":
                    version, manual = data
                    if self.session and not self.session.stopping.is_set():
                        self.pending_update = (version, manual)
                    else:
                        self.show_update_result(version, manual)
        except queue.Empty:
            pass
        if self.session and not self.session.stopping.is_set():
            self.timer.configure(text=tool.format_clock(self.session.seconds))
            self.draw_meters()
        elif self.probe:
            self.draw_setup_meters()
        self.root.after(100, self.poll)

    def draw_meters(self) -> None:
        levels = {"microphone": self.levels[0], "computer": self.levels[1]}
        for key, (canvas, bar, note, last_heard) in self.meters.items():
            if draw_level(canvas, bar, levels[key]) > -45:
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
        self.stop_probe()
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


# A Windows notification ("toast") through the WinRT API that PowerShell 5.1 reaches without any
# package. It shows only for an app ID that a Start menu shortcut carries (installer.iss sets it
# to the one of run()); a click opens the main result.
TOAST_SCRIPT = (
    "$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime];"
    "$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime];"
    "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument; $xml.LoadXml($env:LIVE_TRANSCRIPTION_TOAST);"
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:LIVE_TRANSCRIPTION_APP_ID)"
    ".Show([Windows.UI.Notifications.ToastNotification]::new($xml))")
APP_ID = "transcribe.live"


def notify(root: tk.Tk, title: str, message: str, target: str | None) -> None:
    """Tells that a long processing has ended when the window is not in front: the taskbar button
    flashes and a system notification shows. Nothing when the window is in use."""
    try:
        if root.focus_displayof() is not None:
            return
    except (KeyError, tk.TclError):
        pass  # a messagebox has the focus: the window is in use
    try:
        if os.name == "nt":
            from xml.sax.saxutils import escape, quoteattr
            import pathlib

            class FlashInfo(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("hwnd", ctypes.c_void_p), ("dwFlags", ctypes.c_uint),
                            ("uCount", ctypes.c_uint), ("dwTimeout", ctypes.c_uint)]
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
            # FLASHW_ALL | FLASHW_TIMERNOFG: flashes until the window comes to the front.
            info = FlashInfo(ctypes.sizeof(FlashInfo), hwnd, 0x3 | 0xC, 0, 0)
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
            launch = (f' activationType="protocol" launch={quoteattr(pathlib.Path(target).as_uri())}'
                      if target and os.path.exists(target) else "")
            xml = (f"<toast{launch}><visual><binding template=\"ToastGeneric\"><text>{escape(title)}</text>"
                   f"<text>{escape(message)}</text></binding></visual></toast>")
            env = dict(os.environ, LIVE_TRANSCRIPTION_TOAST=xml, LIVE_TRANSCRIPTION_APP_ID=APP_ID)
            subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", TOAST_SCRIPT],
                             env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        elif sys.platform == "darwin":
            script = f"display notification {json.dumps(message)} with title {json.dumps(title)}"
            subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            import shutil
            if shutil.which("notify-send"):
                subprocess.Popen(["notify-send", title, message], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            root.bell()
    except Exception as error:  # only a convenience
        print(f"Notification not shown: {error}", flush=True)


def clock_seconds(clock: str) -> float:
    """Seconds of "hh:mm:ss" (as transcribe.format_clock writes it); 0 if it is not one."""
    try:
        return sum(int(part) * 60 ** power for power, part in enumerate(reversed(clock.split(":"))))
    except ValueError:
        return 0


def about_minutes(seconds: float) -> str:
    return t("step.minutes", n=round(seconds / 60)) if seconds >= 90 else t("step.under_minutes")


def draw_level(canvas: tk.Canvas, bar, level: float) -> float:
    """Draws an RMS level on a meter, -60..0 dB over its width; returns the level in dB."""
    import math
    decibels = 20 * math.log10(level) if level > 1e-6 else -90
    fraction = min(1.0, max(0.0, (decibels + 60) / 60))
    canvas.coords(bar, 0, 0, int(int(canvas.cget("width")) * fraction), int(canvas.cget("height")))
    return decibels


def primary_label(parent, text: str, colours: tuple[str, str], command, size: int = 13) -> tk.Label:
    """A coloured primary action. Aqua ignores custom colours on buttons, so it is a focusable
    label that reacts to the mouse, Return and Space."""
    normal, hover = colours
    label = tk.Label(parent, text=text, font=(FONT, size, "bold"), background=normal, foreground="white",
                     padx=20, pady=9, cursor="hand2", takefocus=True)
    for sequence in ("<Button-1>", "<Return>", "<space>"):
        label.bind(sequence, lambda _event: command())
    label.bind("<Enter>", lambda _event: label.configure(background=hover))
    label.bind("<Leave>", lambda _event: label.configure(background=normal))
    return label


# The home screen's recent results: only names and folder paths of this computer, never content.
RECENT_FILE = paths.config("recent.local.json")
RECENT_COUNT = 5


def load_recent() -> list[dict]:
    try:
        with open(RECENT_FILE, encoding="utf-8") as source:
            items = json.load(source)
    except (OSError, ValueError):
        return []
    return [item for item in items if isinstance(item, dict) and os.path.isdir(item.get("folder", ""))][:RECENT_COUNT]


def add_recent(kind: str, name: str, folder: str) -> None:
    items = [item for item in load_recent() if os.path.normcase(item["folder"]) != os.path.normcase(folder)]
    items.insert(0, {"kind": kind, "name": name, "folder": folder, "date": time.strftime("%d.%m.%Y %H:%M")})
    try:
        with open(RECENT_FILE, "w", encoding="utf-8") as out:
            json.dump(items[:RECENT_COUNT], out, ensure_ascii=False, indent=1)
    except OSError:
        pass  # only a convenience


def set_icon(root: tk.Tk, recording: bool = False) -> None:
    """Change the Dock/taskbar icon so an active recording is visible outside the window."""
    try:
        name = "live-recording" if recording else "live"
        if os.name == "nt":
            root.iconbitmap(default=os.path.join(ICONS, name + ".ico"))
        else:
            root.icon_image = tk.PhotoImage(file=os.path.join(ICONS, name + ".png"))
            root.iconphoto(True, root.icon_image)
    except tk.TclError:
        pass  # no icon is no reason not to start


def run(args) -> int:
    global FONT
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text on high-DPI screens
            # Its own taskbar button with its own icon, not grouped under python.exe.
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
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
        if app.restart is False:
            return 0
        loaded = None if app.restart is True else app.restart
