"""Live transcription of a meeting while it happens, from the computer's sound and the microphone.

No video is recorded. The sound of every output device (loopback: what the other participants say
in Teams, Zoom, ...) is mixed with the default microphone (what you say). The mix is written to
<folder>/meeting.wav and transcribed in pieces of 8-25 s cut at quiet moments; the text appears in
the console and in <folder>/meeting.live.txt. Enter stops it. Afterwards the recording can be
processed in full by the usual questions (transcribed again at full quality, speakers, check,
summary), or the live text summarized.

The folder is Documents\\Transcripts\\<date time>, or --out-dir.
"""
import ctypes
import gc
import os
import queue
import sys
import threading
import time
import warnings
import wave
from datetime import datetime

import numpy as np

import transcribe as tool

RATE = 16000
BLOCK = RATE // 4  # 0.25 s per read
MIN_CHUNK_SECONDS = 8.0
MAX_CHUNK_SECONDS = 25.0
CUT_SEARCH_SECONDS = 3.0  # where to look for the quietest moment at the end of a chunk
SILENCE_LEVEL = 0.003  # RMS below this is silence: such a chunk is not transcribed
PAUSE_LEVEL = 0.01  # RMS around a cut below this counts as a pause between words
MAX_BACKLOG_BLOCKS = 40  # 10 s: a source further behind than this drops its oldest blocks


def documents_folder() -> str:
    """The user's Documents folder, also when it is redirected (OneDrive)."""
    buffer = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0:  # CSIDL_PERSONAL
        return buffer.value
    return os.path.join(os.path.expanduser("~"), "Documents")


class Source(threading.Thread):
    """Reads one device in real time into a queue of 0.25 s blocks."""

    def __init__(self, device, name: str):
        super().__init__(daemon=True)
        self.device, self.name = device, name
        self.blocks = queue.Queue()
        self.running = True
        self.failed = None

    def run(self) -> None:
        warnings.simplefilter("ignore")  # soundcard warns about discontinuities in silence
        try:
            with self.device.recorder(samplerate=RATE, channels=1, blocksize=BLOCK) as recorder:
                while self.running:
                    self.blocks.put(recorder.record(numframes=BLOCK)[:, 0].astype(np.float32))
        except Exception as error:  # device unplugged or busy: the others go on
            self.failed = error


def open_sources(report) -> tuple[Source, list[Source]]:
    import soundcard as sc

    microphone = Source(sc.default_microphone(), "microphone: " + sc.default_microphone().name)
    loopbacks = []
    for speaker in sc.all_speakers():
        try:
            device = sc.get_microphone(id=str(speaker.id), include_loopback=True)
            loopbacks.append(Source(device, "computer sound: " + speaker.name))
        except Exception:
            report(f"  (cannot listen to {speaker.name}; skipped)")
    for source in [microphone] + loopbacks:
        source.start()
    return microphone, loopbacks


def quietest_cut(audio: np.ndarray, search_seconds: float) -> int:
    """Index of the quietest 0.2 s inside the last search_seconds of audio."""
    window = RATE // 5
    start = max(0, len(audio) - int(search_seconds * RATE))
    best, best_level = len(audio), None
    for position in range(start, len(audio) - window, window // 2):
        level = float(np.mean(np.square(audio[position:position + window])))
        if best_level is None or level < best_level:
            best, best_level = position + window // 2, level
    return best


class LiveTranscriber(threading.Thread):
    """Transcribes queued pieces of audio one after the other and writes the text."""

    def __init__(self, model, args, txt_file, report):
        super().__init__(daemon=True)
        self.model, self.args, self.report = model, args, report
        self.pieces = queue.Queue()
        self.paragraphs = tool.ParagraphWriter(txt_file)
        self.segment_filter = tool.SegmentFilter()
        self.language = None if args.language == tool.MULTILINGUAL else args.language

    def run(self) -> None:
        while True:
            piece = self.pieces.get()
            if piece is None:
                break
            offset, audio = piece
            try:
                self.transcribe(offset, audio)
            except Exception as error:  # one bad piece must not end the meeting's transcript
                self.report(f"  (piece at {tool.format_clock(offset)} not transcribed: {error})")
        self.paragraphs.flush()

    def transcribe(self, offset: float, audio: np.ndarray) -> None:
        multilingual = self.args.language == tool.MULTILINGUAL
        segments, info = self.model.transcribe(
            audio, language=None if multilingual else self.language, multilingual=multilingual,
            vad_filter=True, beam_size=5, hotwords=self.args.hotwords,
            condition_on_previous_text=False)
        for segment in segments:
            text = self.segment_filter.clean(segment.text.strip()) if segment.text.strip() else None
            if not text:
                continue
            if self.language is None and not multilingual:
                self.language = info.language  # detected once, then kept for the whole meeting
                self.report(f"  (language: {info.language})")
            start = offset + segment.start
            self.paragraphs.add(start, offset + segment.end, text)
            self.report(f"[{tool.format_clock(start)}] {text}")


def capture(microphone: Source, loopbacks: list[Source], wav, transcriber: LiveTranscriber,
            stop: threading.Event, report) -> float:
    """Mixes the sources block by block, writes the mix to the WAV file and hands pieces of it
    to the transcriber. The microphone sets the pace; a loopback block that is not there yet is
    silence. Returns the recorded seconds."""
    pending, pending_start, recorded = [], 0.0, 0
    next_status = 300.0

    def hand_over(audio: np.ndarray) -> None:
        if len(audio) and rms(audio) > SILENCE_LEVEL:  # silence is not transcribed
            transcriber.pieces.put((pending_start, audio))

    while not stop.is_set() or not microphone.blocks.empty():
        try:
            mix = microphone.blocks.get(timeout=1.0).copy()
        except queue.Empty:
            if microphone.failed:
                report(f"The microphone stopped: {microphone.failed}")
                break
            continue
        for source in loopbacks:
            while source.blocks.qsize() > MAX_BACKLOG_BLOCKS:
                source.blocks.get_nowait()
            try:
                block = source.blocks.get_nowait()
                mix[:len(block)] += block[:len(mix)]
            except queue.Empty:
                pass  # this device is behind or silent: its part of the mix is silence
        np.clip(mix, -1.0, 1.0, out=mix)
        wav.writeframes((mix * 32767).astype(np.int16).tobytes())
        recorded += len(mix)
        pending.append(mix)

        pending_seconds = sum(len(b) for b in pending) / RATE
        if pending_seconds >= MIN_CHUNK_SECONDS:
            audio = np.concatenate(pending)
            cut = quietest_cut(audio, CUT_SEARCH_SECONDS)
            around_cut = audio[max(0, cut - RATE // 10):cut + RATE // 10]
            # Cut at a real pause; only a piece grown too long is cut wherever it is quietest.
            if rms(around_cut) <= PAUSE_LEVEL or pending_seconds >= MAX_CHUNK_SECONDS:
                hand_over(audio[:cut])
                pending_start += cut / RATE
                pending = [audio[cut:]] if cut < len(audio) else []
            else:
                pending = [audio]
        if recorded / RATE >= next_status:
            report(f"  ... {tool.format_clock(recorded / RATE)} recorded")
            next_status += 300.0
    if pending:
        hand_over(np.concatenate(pending))
    return recorded / RATE


def rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0


def run(args) -> int:
    report = lambda line: print(line, flush=True)
    try:
        import soundcard  # noqa: F401
    except ImportError:
        print("The audio capture package is missing. Run setup.cmd.", file=sys.stderr)
        return 3

    if args.ask and args.language is None:
        choice = tool.ask("Язык встречи:",
                          [f"{n} - {name}" for n, (_, name) in enumerate(tool.LANGUAGE_CHOICES, start=1)],
                          "не знаю, определить по первым фразам", tool.number_in(1, len(tool.LANGUAGE_CHOICES)))
        args.language = tool.LANGUAGE_CHOICES[choice - 1][0] if choice else None

    folder = args.out_dir or os.path.join(documents_folder(), "Transcripts",
                                          datetime.now().strftime("%Y-%m-%d %H-%M"))
    os.makedirs(folder, exist_ok=True)
    wav_path = os.path.join(folder, "meeting.wav")
    txt_path = os.path.join(folder, "meeting.live.txt")

    if os.path.isdir(args.model):
        os.environ["HF_HUB_OFFLINE"] = "1"
    tool.add_cuda_dll_dirs()
    try:
        model = tool.load_model(args.model, "cpu" if args.cpu else "cuda")
    except Exception as error:  # no GPU
        report(f"GPU not usable ({error}); using the CPU, the text will lag behind more.")
        model = tool.load_model(args.model, "cpu")
    args.hotwords = None
    if not args.no_terms:
        terms, files = tool.load_terms(args.terms + tool.DEFAULT_TERMS_FILES)
        if terms:
            args.hotwords = ", ".join(terms)
            tool.report_terms(model, args.hotwords, terms, files)

    microphone, loopbacks = open_sources(report)
    report("\nListening to:")
    for source in [microphone] + loopbacks:
        report(f"  {source.name}")
    report(f"Saving to: {folder}")
    print("\n=== Идёт запись и расшифровка. Нажмите Enter, чтобы остановить. ===\n", flush=True)

    stop = threading.Event()
    with open(txt_path, "w", encoding="utf-8") as txt_file, wave.open(wav_path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        transcriber = LiveTranscriber(model, args, txt_file, report)
        transcriber.start()
        result = {}
        mixer = threading.Thread(target=lambda: result.update(
            seconds=capture(microphone, loopbacks, wav, transcriber, stop, report)), daemon=True)
        mixer.start()
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        print("Stopping; writing the last sentences...", flush=True)
        stop.set()
        for source in [microphone] + loopbacks:
            source.running = False
        mixer.join()
        transcriber.pieces.put(None)
        transcriber.join()

    report(f"\nRecorded {tool.format_clock(result.get('seconds', 0))}.")
    report(f"  live text: {txt_path}")
    report(f"  sound:     {wav_path}")
    filtered = transcriber.segment_filter.report()
    if filtered:
        report(filtered)
    del transcriber, model
    gc.collect()
    return after_meeting(args, wav_path, txt_path)


def after_meeting(args, wav_path: str, txt_path: str) -> int:
    """Offers the full processing of the recording, or a summary of the live text."""
    if not args.ask:
        return 0
    choice = tool.ask("Что сделать с записью?",
                      ["1 - обработать полностью: расшифровать заново целиком (лучше качество), по желанию\n"
                       "      разделить по говорящим, проверить текст и сделать выжимку",
                       "2 - сделать выжимку по тексту, который получился на лету"],
                      "ничего, закончить", tool.number_in(1, 2))
    code = 0
    folder = os.path.dirname(wav_path)
    if choice == 1:
        argv = [wav_path, "--ask", "--srt", "--out-dir", folder]
        if args.language:
            argv += ["--language", args.language]
        code = tool.main(argv)
    elif choice == 2:
        code = tool.main([txt_path, "--ask"])
    keep = tool.ask(f"Оставить звук встречи ({os.path.basename(wav_path)}, нужен для повторной обработки)?",
                    ["1 - оставить", "2 - удалить"], "оставить", tool.number_in(1, 2))
    if keep == 2:
        os.remove(wav_path)
        print("Звук удалён.", flush=True)
    print(f"\nВсё лежит в {folder}", flush=True)
    return code
