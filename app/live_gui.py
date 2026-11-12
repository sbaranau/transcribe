"""The window of the live mode (live-transcribe).

1. Before: language, microphone and output devices, folder; the model loads meanwhile.
2. During: recording light and timer, sound levels of the microphone and the computer, the text
   with timestamps (auto-scrolling unless you scrolled up), the unfinished phrase as a grey draft;
   Stop, open folder, copy text, text size.
3. After: the full processing as check boxes (transcribe again, speakers, check, summary, which
   AI, delete the sound), its progress, and buttons to open the results.

All work runs in background threads; they talk to the window only through a queue that the
window reads every 100 ms.
"""
import contextlib
import ctypes
import gc
import io
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import font as tkfont, messagebox, ttk

import ai_engines
import live
import transcribe as tool

LANGUAGES = [(None, "Определить автоматически"), ("ru", "Русский"), ("en", "Английский"),
             ("de", "Немецкий"), ("fr", "Французский"), (tool.MULTILINGUAL, "Несколько языков")]
NO_MICROPHONE = "Не записывать микрофон"
# The language and microphone chosen last time are offered again (local, not in git).
UI_SETTINGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.local.ini")
PARAGRAPH_PAUSE = 2.0
PARAGRAPH_LONGEST = 30.0
GREY, RED, GREEN = "#6b6b6b", "#c62828", "#2e7d32"
ICONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
# Segoe UI on Windows; on Linux the first of these the system has (set in run()).
FONT = "Segoe UI"
LINUX_FONTS = ["Ubuntu", "Noto Sans", "DejaVu Sans", "Liberation Sans"]
SEARCHING = "Ищу установленные ИИ и проверяю вход..."
# Label colours for the voices of the other side (blue is kept for you).
VOICE_COLOURS = ["#2e7d32", "#c2185b", "#ef6c00", "#6a1b9a", "#00838f", "#8d6e63"]


class QueueWriter(io.TextIOBase):
    """Redirects print() of the processing into the window's log."""

    def __init__(self, events: queue.Queue):
        self.events = events

    def write(self, text: str) -> int:
        if text.strip():
            self.events.put(("log", text.rstrip()))
        return len(text)


class App:
    def __init__(self, root: tk.Tk, args):
        self.root, self.args = root, args
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

        root.title("Расшифровка встречи")
        set_icon(root)
        root.geometry("900x760")
        root.minsize(640, 520)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        style = ttk.Style()
        style.configure("Big.TButton", font=(FONT, 11, "bold"), padding=(14, 6))
        style.configure("TLabel", font=(FONT, 10))
        style.configure("TCheckbutton", font=(FONT, 10))
        style.configure("Head.TLabel", font=(FONT, 14, "bold"))
        style.configure("Note.TLabel", foreground=GREY, font=(FONT, 9))

        self.build_header()
        self.setup_frame = self.build_setup()
        self.meters_frame = self.build_meters()
        self.text_frame = self.build_text()
        self.controls_frame = self.build_controls()
        self.after_frame = None
        self.setup_frame.pack(fill="x", padx=14, pady=(0, 8))
        self.text_frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        threading.Thread(target=self.load_model, daemon=True).start()
        root.after(100, self.poll)

    # --- layout -----------------------------------------------------------------------------------

    def build_header(self) -> None:
        bar = ttk.Frame(self.root, padding=(14, 12, 14, 8))
        bar.pack(fill="x")
        ttk.Label(bar, text="Расшифровка встречи", style="Head.TLabel").pack(side="left")
        self.timer = ttk.Label(bar, text="", font=(FONT, 14))
        self.timer.pack(side="right")
        self.status = ttk.Label(bar, text="Загружаю модель распознавания...", foreground=GREY,
                                font=(FONT, 11))
        self.status.pack(side="right", padx=16)

    def build_setup(self) -> ttk.Frame:
        frame = ttk.LabelFrame(self.root, text=" Перед началом ", padding=12)
        frame.columnconfigure(1, weight=1)

        remembered = self.load_ui_settings()
        ttk.Label(frame, text="Язык встречи:").grid(row=0, column=0, sticky="w", pady=3)
        self.language = ttk.Combobox(frame, state="readonly", values=[name for _, name in LANGUAGES], width=34)
        wanted = self.args.language or remembered.get("language") or None
        default = next((i for i, (code, _) in enumerate(LANGUAGES) if code == wanted), 0)
        self.language.current(default)
        self.language.grid(row=0, column=1, sticky="w", pady=3)

        microphones, default_microphone, speakers = live.list_devices()
        self.microphones = {m.name: m for m in microphones}
        ttk.Label(frame, text="Микрофон (ваш голос):").grid(row=1, column=0, sticky="w", pady=3)
        self.microphone = ttk.Combobox(frame, state="readonly", width=50,
                                       values=list(self.microphones) + [NO_MICROPHONE])
        last_microphone = remembered.get("microphone")
        if last_microphone in self.microphones or last_microphone == NO_MICROPHONE:
            self.microphone.set(last_microphone)
        else:
            self.microphone.set(default_microphone.name if default_microphone else NO_MICROPHONE)
        self.microphone.grid(row=1, column=1, sticky="w", pady=3)

        ttk.Label(frame, text="Звук компьютера\n(собеседники):").grid(row=2, column=0, sticky="nw", pady=3)
        box = ttk.Frame(frame)
        box.grid(row=2, column=1, sticky="w", pady=3)
        self.speakers = []
        for speaker in speakers:
            var = tk.BooleanVar(value=True)
            ttk.Checkbutton(box, text=speaker.name, variable=var).pack(anchor="w")
            self.speakers.append((speaker, var))
        ttk.Label(box, text="Отмечены все устройства: так собеседники будут слышны, куда бы ни шёл звук созвона.",
                  style="Note.TLabel", wraplength=520).pack(anchor="w")

        ttk.Label(frame, text="Папка:").grid(row=3, column=0, sticky="w", pady=3)
        self.folder_label = ttk.Label(frame, text=os.path.join(self.base_folder, "<дата время>"))
        self.folder_label.grid(row=3, column=1, sticky="w", pady=3)

        ttk.Label(frame, text="Предупредите участников, что встреча расшифровывается.",
                  foreground=RED).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 4))
        self.start_button = ttk.Button(frame, text="●  Начать запись", style="Big.TButton",
                                       command=self.start, state="disabled")
        self.start_button.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        return frame

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
        settings["live"] = {key: value for key, value in values.items() if value is not None}
        try:
            with open(UI_SETTINGS, "w", encoding="utf-8") as out:
                settings.write(out)
        except OSError:
            pass  # only a convenience

    def build_meters(self) -> ttk.Frame:
        frame = ttk.Frame(self.root)
        self.meters = {}
        for row, (key, title) in enumerate((("microphone", "Микрофон"), ("computer", "Звук компьютера"))):
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
            text="Собеседников слышно, а ваш микрофон молчит уже больше 20 секунд. Проверьте, что он не "
                 "выключен (кнопка на гарнитуре или в программе созвона) и что здесь выбран тот же "
                 "микрофон, что в программе созвона.")
        return frame

    def build_text(self) -> ttk.Frame:
        frame = ttk.Frame(self.root)
        self.text = tk.Text(frame, wrap="word", font=(FONT, self.text_size), padx=12, pady=10,
                            relief="flat", background="#fbfbfb", spacing3=4, height=8)
        scroll = ttk.Scrollbar(frame, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.apply_text_size()
        self.text.insert("end", "Здесь появится текст встречи.\n", ("hint",))
        self.text.configure(state="disabled")
        self.to_end = ttk.Button(frame, text="↓ К концу", command=self.scroll_to_end)
        return frame

    def build_controls(self) -> ttk.Frame:
        frame = ttk.Frame(self.root)
        self.stop_button = ttk.Button(frame, text="■  Остановить", style="Big.TButton", command=self.stop)
        self.stop_button.pack(side="left")
        ttk.Button(frame, text="Открыть папку", command=self.open_folder).pack(side="left", padx=(12, 0))
        ttk.Button(frame, text="Копировать текст", command=self.copy_text).pack(side="left", padx=(6, 0))
        ttk.Button(frame, text="A+", width=4, command=lambda: self.change_size(1)).pack(side="right")
        ttk.Button(frame, text="A−", width=4, command=lambda: self.change_size(-1)).pack(side="right", padx=(0, 4))
        return frame

    def apply_text_size(self) -> None:
        self.text.configure(font=(FONT, self.text_size))
        self.text.tag_configure("time", foreground=GREY, font=(FONT, max(8, self.text_size - 3)))
        self.text.tag_configure("draft", foreground="#9a9a9a", font=(FONT, self.text_size, "italic"))
        self.text.tag_configure("hint", foreground=GREY)
        self.text.tag_configure("info", foreground=GREY, font=(FONT, max(8, self.text_size - 3), "italic"))
        self.text.tag_configure("me", foreground="#1565c0", font=(FONT, self.text_size, "bold"))
        self.text.tag_configure("others", foreground="#2e7d32", font=(FONT, self.text_size, "bold"))
        for number, colour in enumerate(VOICE_COLOURS):
            self.text.tag_configure(f"voice{number}", foreground=colour, font=(FONT, self.text_size, "bold"))

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
            messagebox.showwarning("Нечего записывать", "Выберите микрофон или хотя бы одно устройство звука.")
            return
        language = LANGUAGES[self.language.current()][0]
        self.args.language = language
        self.save_ui_settings({"language": language or "", "microphone": self.microphone.get()})
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
            messagebox.showerror("Не удалось начать запись", str(error))
            return
        self.setup_frame.pack_forget()
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
        self.status.configure(text="●  Идёт запись", foreground=RED)
        self.folder = folder

    def set_levels(self, microphone: float, computer: float) -> None:
        self.levels = (max(microphone, self.levels[0] * 0.6), max(computer, self.levels[1] * 0.6))

    def stop(self) -> None:
        if not self.session or self.session.stopping.is_set():
            return  # a second click while stopping does nothing
        self.stop_button.configure(state="disabled")
        self.status.configure(text="Останавливаю, дописываю последние фразы...", foreground=GREY)
        threading.Thread(target=self.finish_session, daemon=True).start()

    def finish_session(self) -> None:
        self.session.stop()
        self.events.put(("stopped", None))
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
        if new_paragraph:
            gap = "\n\n" if self.last_end is not None else ""
            name = (f"{label}: ", (self.label_tag(label),)) if label else ("", ())
            self.append_final(gap, (), f"[{tool.format_clock(start)}]  ", ("time",), *name, text, ())
            self.paragraph_start = start
        else:
            self.append_final(" " + text, ())
        self.last_end, self.last_label = end, label
        self.render_drafts()

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
        shown = 0
        for label, text in self.drafts.items():
            if text:
                gap = "\n\n" if shown or self.text.compare("draft", ">", "1.0") else ""
                self.text.insert("end-1c", gap + (f"{label}: " if label else "") + text + " …", ("draft",))
                shown += 1
        self.text.configure(state="disabled")
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
        self.meters_frame.pack_forget()
        self.controls_frame.pack_forget()
        self.text_frame.pack_forget()
        seconds = self.session.seconds
        self.status.configure(text=f"Запись остановлена: {tool.format_clock(seconds)}", foreground=GREEN)
        self.timer.configure(text="")
        self.model = self.session.model = None
        gc.collect()

        frame = ttk.LabelFrame(self.root, text=" Что дальше ", padding=12)
        self.after_frame = frame
        frame.pack(fill="x", padx=14, pady=(0, 8))
        self.text_frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        ttk.Label(frame, text=f"Текст на лету сохранён: {self.session.txt_path}", style="Note.TLabel",
                  wraplength=760).grid(row=0, column=0, columnspan=3, sticky="w")

        self.redo = tk.BooleanVar(value=True)
        self.split = tk.BooleanVar(value=False)
        self.count = tk.StringVar(value="0")
        self.check = tk.BooleanVar(value=False)
        self.summary = tk.BooleanVar(value=False)
        self.delete_sound = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Расшифровать запись заново целиком (точнее, чем на лету)",
                        variable=self.redo, command=self.refresh_after).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 2))
        call = len(self.session.streams) >= 2 if hasattr(self.session, "streams") else False
        self.is_call = call  # a call has "Вы" / "Собеседники" labels even without the separation
        self.split_box = ttk.Checkbutton(
            frame, text="Разделить собеседников по голосам, всего человек:" if call else
            "Разделить по говорящим, человек:", variable=self.split, command=self.refresh_after)
        self.split_box.grid(row=2, column=0, sticky="w", padx=(22, 0), pady=2)
        self.count_box = ttk.Spinbox(frame, from_=0, to=20, width=4, textvariable=self.count)
        self.count_box.grid(row=2, column=1, sticky="w", pady=2)
        ttk.Label(frame, text="вместе с вами; 0 = не знаю" if call else "0 = не знаю",
                  style="Note.TLabel").grid(row=2, column=2, sticky="w", padx=6)
        self.check_box = ttk.Checkbutton(frame, text="Проверить текст с помощью ИИ: имена вместо номеров, реплики с чужой меткой",
                                         variable=self.check, command=self.refresh_after)
        self.check_box.grid(row=3, column=0, columnspan=3, sticky="w", padx=(22, 0), pady=2)
        ttk.Checkbutton(frame, text="Сделать выжимку с помощью ИИ", variable=self.summary,
                        command=self.refresh_after).grid(row=4, column=0, columnspan=3, sticky="w", pady=2)

        self.ai_row = ttk.Frame(frame)
        self.ai_row.grid(row=5, column=0, columnspan=3, sticky="w", padx=(22, 0), pady=(4, 2))
        ttk.Label(self.ai_row, text="ИИ:").pack(side="left")
        self.ai_choice = ttk.Combobox(self.ai_row, state="disabled", width=52)
        self.ai_choice.pack(side="left", padx=6)
        self.ai_note = ttk.Label(frame, text=SEARCHING, style="Note.TLabel", wraplength=760)
        self.ai_note.grid(row=6, column=0, columnspan=3, sticky="w", padx=(22, 0))
        self.path_row = ttk.Frame(frame)
        ttk.Label(self.path_row, text="Путь к claude или codex (или к их папке), или адрес локального "
                  "сервера, например http://127.0.0.1:11434:", wraplength=740).pack(anchor="w")
        entry_line = ttk.Frame(self.path_row)
        entry_line.pack(anchor="w", pady=(2, 0))
        self.path_entry = ttk.Entry(entry_line, width=56)
        self.path_entry.pack(side="left")
        ttk.Button(entry_line, text="Проверить", command=self.try_path).pack(side="left", padx=6)
        self.ai_warning = ttk.Label(frame, foreground=RED, wraplength=760, text=(
            "Текст уйдёт в выбранный ИИ под вашим аккаунтом (у локальной модели останется на "
            "компьютере), поэтому только если ваши правила это разрешают."))
        self.ai_warning.grid(row=8, column=0, columnspan=3, sticky="w", padx=(22, 0), pady=(2, 4))

        ttk.Checkbutton(frame, text="Удалить звук встречи (meeting.wav) после обработки",
                        variable=self.delete_sound).grid(row=9, column=0, columnspan=3, sticky="w", pady=2)
        buttons = ttk.Frame(frame)
        buttons.grid(row=10, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.run_button = ttk.Button(buttons, text="Выполнить", style="Big.TButton", command=self.run_processing)
        self.run_button.pack(side="left")
        ttk.Button(buttons, text="Открыть папку", command=self.open_folder).pack(side="left", padx=(12, 0))
        ttk.Button(buttons, text="Закрыть", command=self.root.destroy).pack(side="left", padx=(6, 0))
        self.result_buttons = ttk.Frame(buttons)
        self.result_buttons.pack(side="left", padx=(18, 0))
        self.refresh_after()
        threading.Thread(target=lambda: self.events.put(
            ("ai", ai_engines.verify_engines(ai_engines.find_engines()))), daemon=True).start()

    def refresh_after(self) -> None:
        redo = self.redo.get()
        self.split_box.configure(state="normal" if redo else "disabled")
        self.count_box.configure(state="normal" if redo and self.split.get() else "disabled")
        can_check = redo and (self.split.get() or getattr(self, "is_call", False))
        if not can_check:
            self.check.set(False)
        self.check_box.configure(state="normal" if can_check else "disabled")
        needs_ai = self.check.get() or self.summary.get()
        for widget in (self.ai_row, self.ai_note, self.ai_warning):
            if needs_ai and (widget is not self.ai_note or widget.cget("text")):
                widget.grid()
            else:
                widget.grid_remove()
        if needs_ai and not self.found_ai and self.ai_note.cget("text") != SEARCHING:
            self.path_row.grid(row=7, column=0, columnspan=3, sticky="w", padx=(22, 0), pady=2)
        else:
            self.path_row.grid_remove()

    def show_ai(self, found: dict, left_out: dict) -> None:
        """Only tools that are installed and logged in are offered; the others are named with
        what to do."""
        self.found_ai = found
        self.ai_keys = list(found)
        self.ai_choice.configure(values=[ai_engines.describe(e, found[e]) for e in self.ai_keys],
                                 state="readonly" if found else "disabled")
        notes = [f"{ai_engines.TITLES[e]}: установлен, но {reason}" for e, reason in left_out.items()]
        if found:
            self.ai_choice.current(0)
        else:
            notes.insert(0, "Нет ИИ, готового к работе (установленного и с выполненным входом).")
        self.ai_note.configure(text="\n".join(notes))
        self.refresh_after()

    def try_path(self) -> None:
        result = ai_engines.classify(self.path_entry.get())
        if not result:
            messagebox.showwarning("Не найдено", "По этому пути не нашёлся ни claude, ни codex, и локальный сервер не отвечает.")
            return
        usable, left_out = ai_engines.verify_engines(dict([result]))
        if not usable:
            messagebox.showwarning("Вход не выполнен", f"{ai_engines.TITLES[result[0]]} найден, но {left_out[result[0]]}.")
            return
        ai_engines.remember(*result)
        self.show_ai(usable, {})

    def run_processing(self) -> None:
        if not (self.redo.get() or self.summary.get()):
            messagebox.showinfo("Нечего делать", "Отметьте, что сделать с записью, или нажмите «Закрыть».")
            return
        if (self.check.get() or self.summary.get()) and not self.found_ai:
            if self.ai_note.cget("text") == SEARCHING:
                messagebox.showinfo("Подождите", "Ещё проверяю, какие ИИ установлены и где выполнен вход. Это несколько секунд.")
            else:
                messagebox.showwarning("Нет ИИ", "Для проверки и выжимки нужен ИИ: укажите путь или снимите эти галочки.")
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
        if ai:
            argv += ["--ai", ai]
        self.run_button.configure(state="disabled")
        self.status.configure(text="Обработка...", foreground=GREY)
        self.text.configure(state="normal")
        self.text.insert("end", "\n\n— Обработка записи —\n", ("info",))
        self.text.configure(state="disabled")
        self.text.see("end")
        threading.Thread(target=self.process, args=(argv,), daemon=True).start()

    def process(self, argv: list[str]) -> None:
        writer = QueueWriter(self.events)
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                code = tool.main(argv)
        except Exception as error:
            self.events.put(("log", f"FAILED: {error}"))
            code = 1
        if code == 0 and self.delete_sound.get() and os.path.exists(self.session.wav_path):
            os.remove(self.session.wav_path)
            self.events.put(("log", "Звук встречи удалён."))
        self.events.put(("processed", code))

    def show_results(self, code: int) -> None:
        folder = os.path.dirname(self.session.wav_path)
        self.status.configure(text="Готово" if code == 0 else "Готово, но с ошибками (см. текст)",
                              foreground=GREEN if code == 0 else RED)
        self.run_button.configure(state="normal")
        for child in self.result_buttons.winfo_children():
            child.destroy()
        for name, title in (("meeting.checked.txt", "Проверенный текст"), ("meeting.txt", "Текст"),
                            ("meeting.summary.md", "Выжимку"), ("meeting.live.summary.md", "Выжимку")):
            path = os.path.join(folder, name)
            if os.path.exists(path) and not any(b.cget("text") == f"Открыть: {title}" for b in self.result_buttons.winfo_children()):
                ttk.Button(self.result_buttons, text=f"Открыть: {title}",
                           command=lambda p=path: tool.open_path(p)).pack(side="left", padx=(0, 6))

    # --- events -----------------------------------------------------------------------------------

    def poll(self) -> None:
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "model":
                    self.model, self.hotwords, note = data
                    self.status.configure(text="Готово к записи", foreground=GREEN)
                    self.start_button.configure(state="normal")
                elif kind == "model_failed":
                    self.status.configure(text="Модель не загрузилась", foreground=RED)
                    messagebox.showerror("Ошибка", f"Модель распознавания не загрузилась:\n{data}\n\nЗапустите {tool.SETUP_HINT}.")
                elif kind == "final":
                    self.add_final(*data)
                elif kind == "draft":
                    self.set_draft(*data)
                elif kind == "mic_silent":
                    self.show_mic_warning(data)
                elif kind == "info":
                    self.add_info(data)
                elif kind == "stopped":
                    self.show_after()
                elif kind == "ai":
                    self.show_ai(*data)
                elif kind == "log":
                    self.text.configure(state="normal")
                    self.text.insert("end", data + "\n", ("info",))
                    self.text.configure(state="disabled")
                    self.text.see("end")
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
        for key, level in zip(("microphone", "computer"), self.levels):
            canvas, bar, note, last_heard = self.meters[key]
            decibels = 20 * math.log10(level) if level > 1e-6 else -90
            fraction = min(1.0, max(0.0, (decibels + 60) / 60))
            width = int(canvas.cget("width"))
            canvas.coords(bar, 0, 0, int(width * fraction), 14)
            if decibels > -45:
                last_heard[0] = time.time()
                note.configure(text="")
            elif time.time() - last_heard[0] > 15:
                note.configure(text="тишина")

    def on_close(self) -> None:
        if self.session and not self.session.stopping.is_set():
            if not messagebox.askyesno("Идёт запись", "Остановить запись и закрыть окно?\nТекст и звук сохранятся."):
                return
            self.status.configure(text="Останавливаю...", foreground=GREY)
            self.root.update()
            self.session.stop()
        self.root.destroy()


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
    root = tk.Tk()
    if os.name != "nt":
        families = set(tkfont.families(root))
        FONT = next((name for name in LINUX_FONTS if name in families), "TkDefaultFont")
    App(root, args)
    root.mainloop()
    return 0
