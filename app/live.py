"""Live transcription of a meeting while it happens, from the computer's sound and the microphone.

No video is recorded. The microphone (what you say) and the sound of the chosen output devices
(loopback: what the other participants say in Teams, Zoom, ...) are kept as two streams:

- each stream is cut into pieces of 20-29 s at pauses and transcribed on its own, so a quiet
  voice is not lost under a loud one, and the text gets the labels "Вы" / "Собеседники";
- the microphone gets an automatic gain: Teams and other call programs may turn the system
  microphone level down during a call (they amplify their own copy), so the raw microphone can be
  20-30 dB quieter than the other side;
- words of the other side that the microphone picks up from loudspeakers (echo) are taken out
  of the microphone stream when the computer stream has the same words at the same time;
- both go to <folder>/meeting.wav as two channels (left: microphone after the gain, right:
  computer sound), and the final text to <folder>/meeting.live.txt, in time order.

Between pieces, the unfinished phrase of each stream is transcribed quickly as a draft.
LiveSession is the engine; live_gui.py is the window (the default of live-transcribe.cmd), and
run() below is a plain console front end (--live --console).
"""
import collections
import ctypes
import difflib
import gc
import os
import queue
import re
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
# Final pieces of 20-29 s, close to Whisper's 30 s window. Replaying recordings through this
# engine and comparing with a full transcription of the same file (2026-11-12): 8-25 s pieces
# agreed 42% (84 s Russian call) and 88.9% (17 min AMI meeting), 15-28 s 74% / 92.3%, 20-29 s
# 91% / 93.0%. The drafts keep the text on screen within seconds meanwhile.
MIN_CHUNK_SECONDS = 20.0
MAX_CHUNK_SECONDS = 29.0
CUT_SEARCH_SECONDS = 3.0  # where to look for the quietest moment at the end of a piece
SILENCE_LEVEL = 0.003  # RMS below this is silence: such a piece is not transcribed
PAUSE_LEVEL = 0.01  # RMS around a cut below this counts as a pause between words
MAX_BACKLOG_BLOCKS = 40  # 10 s: a device further behind than this drops its oldest blocks
# End of the previous final text given to Whisper as a prompt; 0 = none. With 20-29 s pieces it
# gained nothing measurable (91% / 93.6%) and may repeat words of the prompt, so it is off.
CONTEXT_CHARS = 0
DRAFT_EVERY_SECONDS = 2.0  # how often the unfinished phrase is shown as a draft
DRAFT_MIN_NEW_SECONDS = 1.0  # ... if at least this much new sound came since the last draft
# Microphone gain: the speech level (90th percentile of the louder 0.25 s blocks over the last
# 20 s) is brought to about -20 dB, by at most 30x (+30 dB), changing gradually.
MIC_TARGET_LEVEL = 0.1
MIC_MAX_GAIN = 30.0
AGC_WINDOW_BLOCKS = 80
# Echo: runs of at least ECHO_MIN_RUN words of a microphone phrase that match what the computer
# played within 2 s are removed; a phrase that is ECHO_SIMILARITY or more echo with nothing of its
# own left is dropped.
ECHO_MIN_RUN = 3
ECHO_SIMILARITY = 0.6
# The window warns when the other side is heard but the microphone stays below this level.
MIC_SILENT_LEVEL = 0.0025  # about -52 dB
MIC_SILENT_SECONDS = 20.0
# (you, the other side as a whole, one person of the other side) per language; shared with the
# full processing of the recording, so both use the same labels.
STREAM_LABELS = tool.STREAM_LABELS
# Voices of the other side told apart while it happens: each phrase's voice embedding is compared
# with the voices heard so far. Measured on three AMI meetings (4 people each, reference speaker
# timing; phrases labelled in time order with only what came before): threshold 0.42 with a new
# voice only from phrases of 2.5 s or more found exactly 4 voices in all three and put 92% of the
# words to the right person; 0.6-0.7 made 6-36 voices, 0.38 or 4 s merged people. Inside the live
# engine (phrases from 20-29 s pieces) the same meetings gave 4, 5 and 3 voices and 82, 73 and 93%
# of the speech time to the right person; the full processing afterwards does better.
LIVE_SAME_VOICE = 0.42
LIVE_NEW_VOICE_SECONDS = 2.5
LIVE_EMBED_SECONDS = 0.8  # shorter phrases keep the voice of the phrase before
# Cutting a phrase where its words pause (0.25 or 0.4 s) and labelling the parts separately was
# tried: 81/75/95% against 82/73/93% of the speech time right, but fewer voices found and parts
# without a voice, so phrases are labelled whole (0 = not cut).
LIVE_SPLIT_PAUSE = 0


def documents_folder() -> str:
    """The user's Documents folder, also when it is redirected (OneDrive)."""
    buffer = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0:  # CSIDL_PERSONAL
        return buffer.value
    return os.path.join(os.path.expanduser("~"), "Documents")


def new_folder() -> str:
    return os.path.join(documents_folder(), "Transcripts", datetime.now().strftime("%Y-%m-%d %H-%M"))


def rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def list_devices() -> tuple[list, object, list]:
    """(microphones, default microphone, output devices)."""
    import soundcard as sc
    return sc.all_microphones(), sc.default_microphone(), sc.all_speakers()


class Source(threading.Thread):
    """Reads one device in real time into a queue of 0.25 s blocks."""

    def __init__(self, device, name: str, loopback: bool):
        super().__init__(daemon=True)
        self.device, self.name, self.loopback = device, name, loopback
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


class AutoGain:
    """Brings the speech level of a stream to MIC_TARGET_LEVEL, gradually."""

    def __init__(self):
        self.levels = collections.deque(maxlen=AGC_WINDOW_BLOCKS)
        self.gain = 1.0

    def apply(self, block: np.ndarray) -> np.ndarray:
        self.levels.append(rms(block))
        if len(self.levels) >= 8:
            levels = np.array(self.levels)
            floor = np.percentile(levels, 10)
            speech = levels[levels > max(floor * 3, 1e-4)]
            if len(speech) >= 4:
                wanted = min(MIC_MAX_GAIN, max(1.0, MIC_TARGET_LEVEL / float(np.percentile(speech, 90))))
                self.gain += (wanted - self.gain) * 0.05
        return block * self.gain


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


class OnlineVoices:
    """Tells the voices of one stream apart phrase by phrase, from the voices heard so far."""

    def __init__(self):
        import sherpa_onnx
        self.extractor = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=tool.EMBEDDING_MODEL, num_threads=2))
        self.voices = []  # weighted sums of embeddings
        self.previous = None

    def voice_of(self, audio: np.ndarray) -> int | None:
        """Number of the voice (0, 1, ...) of a phrase; None until a voice is known."""
        seconds = len(audio) / RATE
        if seconds < LIVE_EMBED_SECONDS:
            return self.previous
        stream = self.extractor.create_stream()
        stream.accept_waveform(RATE, audio)
        stream.input_finished()
        vector = np.array(self.extractor.compute(stream))
        vector /= np.linalg.norm(vector)
        similarities = [float(v / np.linalg.norm(v) @ vector) for v in self.voices]
        best = int(np.argmax(similarities)) if similarities else None
        if best is not None and (similarities[best] >= LIVE_SAME_VOICE or seconds < LIVE_NEW_VOICE_SECONDS):
            self.voices[best] = self.voices[best] + vector * min(seconds, 10.0)
        elif best is None and seconds < LIVE_NEW_VOICE_SECONDS:
            return self.previous  # wait for a longer phrase before the first voice
        else:
            self.voices.append(vector * min(seconds, 10.0))
            best = len(self.voices) - 1
        self.previous = best
        return best


class Stream:
    """One sound stream ("mic" or "computer") being cut into pieces."""

    def __init__(self, key: str):
        self.key = key
        self.pending, self.pending_start = [], 0.0  # sound not yet handed over, read by drafts
        self.done_until = 0.0  # the final text of this stream is complete up to here
        self.last_draft_length = 0


class LiveSession:
    """Records and transcribes until stop(). Callbacks run in background threads:
    on_final(start, end, label or None, text), on_draft(label or None, text or ""),
    on_levels(microphone, computer), on_mic_silent(bool), on_info(message)."""

    def __init__(self, model, folder: str, language: str | None, hotwords: str | None,
                 microphone, speakers: list, on_final=None, on_draft=None, on_levels=None,
                 on_info=None, on_mic_silent=None, streams: tuple[str, ...] | None = None):
        self.model, self.folder, self.hotwords = model, folder, hotwords
        self.multilingual = language == tool.MULTILINGUAL
        self.language = None if self.multilingual else language
        self.on_final = on_final or (lambda start, end, label, text: None)
        self.on_draft = on_draft or (lambda label, text: None)
        self.on_levels = on_levels or (lambda microphone, computer: None)
        self.on_mic_silent = on_mic_silent or (lambda silent: None)
        self.on_info = on_info or (lambda message: None)
        self.wav_path = os.path.join(folder, "meeting.wav")
        self.txt_path = os.path.join(folder, "meeting.live.txt")
        self.sources = []
        if microphone is not None:
            self.sources.append(Source(microphone, "microphone: " + microphone.name, False))
        if speakers:
            import soundcard as sc
            for speaker in speakers:
                try:
                    device = sc.get_microphone(id=str(speaker.id), include_loopback=True)
                    self.sources.append(Source(device, "computer sound: " + speaker.name, True))
                except Exception as error:
                    self.on_info(f"Cannot listen to {speaker.name}: {error}")
        if streams is None:
            streams = tuple(key for key, present in (
                ("mic", microphone is not None), ("computer", any(s.loopback for s in self.sources))) if present)
        self.streams = {key: Stream(key) for key in streams}
        # The stream whose voices are told apart: the other side in a call, or everyone when only
        # one stream is recorded (a meeting in a room).
        self.voice_stream = "computer" if "computer" in self.streams else next(iter(self.streams), None)
        self.voices = None
        if self.voice_stream and os.path.isfile(tool.EMBEDDING_MODEL):
            try:
                self.voices = OnlineVoices()
            except Exception as error:  # without voices the labels are per stream only
                self.on_info(f"Voices are not told apart: {error}")
        self.gain = AutoGain()
        self.pieces = queue.Queue()
        self.stopping = threading.Event()
        self.lock = threading.Lock()
        self.recorded = 0
        self.segment_filter = tool.SegmentFilter()
        self.waiting = []  # final segments not yet written: (start, end, key, text)
        self.recent_computer = collections.deque(maxlen=200)  # (start, end, words) for the echo check
        self.echoes = 0
        self.mic_silent_since = None
        self.mic_silent_shown = False

    @property
    def seconds(self) -> float:
        return self.recorded / RATE

    def label(self, key: str, voice: int | None = None) -> str | None:
        """"Вы" for the microphone in a call; "Собеседник 2" for a voice of the other side (or
        "Говорящий 2" with one stream); the side as a whole when the voice is not known."""
        mine, others, one_of_others = STREAM_LABELS.get(self.language or "", ("You", "Others", "Speaker"))
        if len(self.streams) >= 2 and key == "mic":
            return mine
        if voice is not None:
            name = one_of_others if len(self.streams) >= 2 else tool.speaker_label(self.language)
            return f"{name} {voice + 1}"
        return others if len(self.streams) >= 2 else None

    # --- start and stop -----------------------------------------------------------------------

    def open_outputs(self) -> None:
        os.makedirs(self.folder, exist_ok=True)
        self.txt_file = open(self.txt_path, "w", encoding="utf-8")
        self.paragraphs = tool.ParagraphWriter(self.txt_file)
        self.wav = wave.open(self.wav_path, "wb")
        # A call: left the microphone after the gain, right the computer sound (the full processing
        # tells your words by these channels). One stream only (a room): mono.
        self.wav.setnchannels(2 if len(self.streams) >= 2 else 1)
        self.wav.setsampwidth(2)
        self.wav.setframerate(RATE)
        self.worker = threading.Thread(target=self.work_loop, daemon=True)
        self.worker.start()

    def start(self) -> None:
        if not self.sources:
            raise RuntimeError("nothing to listen to")
        self.open_outputs()
        for source in self.sources:
            source.start()
        self.mixer = threading.Thread(target=self.mix_loop, daemon=True)
        self.mixer.start()

    def stop(self) -> None:
        """Stops recording, transcribes what is left and closes the files (blocks until done)."""
        self.stopping.set()
        for source in self.sources:
            source.running = False
        if hasattr(self, "mixer"):
            self.mixer.join()
        self.finish()

    def finish(self) -> None:
        """Hands over what is left of every stream, waits for the text, closes the files."""
        for stream in self.streams.values():
            with self.lock:
                rest = np.concatenate(stream.pending) if stream.pending else np.zeros(0, np.float32)
                start, stream.pending = stream.pending_start, []
            self.hand_over(stream, start, rest)
        self.pieces.put(None)
        self.worker.join()
        self.write_ready(final=True)
        self.paragraphs.flush()
        self.txt_file.close()
        self.wav.close()

    # --- recording ----------------------------------------------------------------------------

    def mix_loop(self) -> None:
        """Reads the devices block by block; the first device (the microphone if any) sets the
        pace, a block another device has not delivered yet is silence."""
        lead, others = self.sources[0], self.sources[1:]
        warned = set()
        while not self.stopping.is_set() or not lead.blocks.empty():
            try:
                first = lead.blocks.get(timeout=1.0)
            except queue.Empty:
                if lead.failed:
                    self.on_info(f"{lead.name} stopped: {lead.failed}")
                    break
                continue
            microphone = None if lead.loopback else first
            computer = first.copy() if lead.loopback else np.zeros_like(first)
            for source in others:
                while source.blocks.qsize() > MAX_BACKLOG_BLOCKS:
                    source.blocks.get_nowait()
                try:
                    block = source.blocks.get_nowait()
                    computer[:len(block)] += block[:len(computer)]
                except queue.Empty:
                    if source.failed and source.name not in warned:
                        warned.add(source.name)
                        self.on_info(f"{source.name} stopped: {source.failed}")
            self.feed(microphone, computer if "computer" in self.streams else None)

    def feed(self, microphone: np.ndarray | None, computer: np.ndarray | None) -> None:
        """One 0.25 s block of each stream (None for a stream that is not recorded)."""
        length = len(microphone) if microphone is not None else len(computer)
        raw_level = rms(microphone) if microphone is not None else 0.0
        computer_level = rms(computer) if computer is not None else 0.0
        self.watch_microphone(raw_level, computer_level)
        if microphone is not None:
            microphone = np.clip(self.gain.apply(microphone), -1.0, 1.0)
        # The meter shows the microphone after the gain, i.e. what is transcribed: a call program
        # that turned the system level down would otherwise make it look silent. Below the silence
        # level it shows the raw level, so amplified background noise does not look like speech.
        if microphone is None:
            meter = 0.0
        else:
            meter = rms(microphone) if raw_level >= MIC_SILENT_LEVEL else raw_level
        self.on_levels(meter, computer_level)
        if computer is not None:
            computer = np.clip(computer, -1.0, 1.0)
        left = microphone if microphone is not None else np.zeros(length, np.float32)
        right = computer if computer is not None else np.zeros(length, np.float32)
        if len(self.streams) >= 2:
            frames = np.empty(length * 2, np.float32)
            frames[0::2], frames[1::2] = left, right
        else:
            frames = left if "mic" in self.streams else right
        self.wav.writeframes((frames * 32767).astype(np.int16).tobytes())
        self.recorded += length
        if microphone is not None and "mic" in self.streams:
            self.add_sound(self.streams["mic"], microphone.astype(np.float32))
        if computer is not None and "computer" in self.streams:
            self.add_sound(self.streams["computer"], computer.astype(np.float32))

    def watch_microphone(self, microphone: float, computer: float) -> None:
        """Tells the window when the other side is heard but the microphone stays silent."""
        if "mic" not in self.streams or "computer" not in self.streams:
            return
        now = self.recorded / RATE
        if microphone >= MIC_SILENT_LEVEL:
            self.mic_silent_since = None
        elif computer > PAUSE_LEVEL and self.mic_silent_since is None:
            self.mic_silent_since = now
        silent = self.mic_silent_since is not None and now - self.mic_silent_since >= MIC_SILENT_SECONDS
        if silent != self.mic_silent_shown:
            self.mic_silent_shown = silent
            self.on_mic_silent(silent)

    def add_sound(self, stream: Stream, block: np.ndarray) -> None:
        with self.lock:
            stream.pending.append(block)
            pending_seconds = sum(len(b) for b in stream.pending) / RATE
            if pending_seconds < MIN_CHUNK_SECONDS:
                return
            audio = np.concatenate(stream.pending)
            cut = quietest_cut(audio, CUT_SEARCH_SECONDS)
            around_cut = audio[max(0, cut - RATE // 10):cut + RATE // 10]
            # Cut at a real pause; only a piece grown too long is cut wherever it is quietest.
            if rms(around_cut) > PAUSE_LEVEL and pending_seconds < MAX_CHUNK_SECONDS:
                stream.pending = [audio]
                return
            start = stream.pending_start
            stream.pending_start += cut / RATE
            stream.pending = [audio[cut:]] if cut < len(audio) else []
        self.hand_over(stream, start, audio[:cut])

    def hand_over(self, stream: Stream, start: float, audio: np.ndarray) -> None:
        end = start + len(audio) / RATE
        if len(audio) and rms(audio) > SILENCE_LEVEL:
            self.pieces.put((stream.key, start, end, audio))
        else:  # silence is not transcribed, but the stream's text is complete up to its end
            self.pieces.put((stream.key, start, end, None))

    # --- transcription ------------------------------------------------------------------------

    def work_loop(self) -> None:
        last_draft_time = 0.0
        while True:
            try:
                piece = self.pieces.get(timeout=0.2)
            except queue.Empty:
                piece = False
            if piece is None:
                break
            if piece:
                key, start, end, audio = piece
                if audio is not None:
                    try:
                        self.transcribe_final(key, start, audio)
                    except Exception as error:  # one bad piece must not end the transcript
                        self.on_info(f"Piece at {tool.format_clock(start)} not transcribed: {error}")
                self.streams[key].done_until = end
                self.streams[key].last_draft_length = 0
                self.on_draft(self.label(key), "")
                self.write_ready()
                continue
            if self.stopping.is_set() or time.time() - last_draft_time < DRAFT_EVERY_SECONDS:
                continue
            last_draft_time = time.time()
            self.make_draft()

    def make_draft(self) -> None:
        """Drafts the stream with the most new unfinished sound."""
        best, best_audio = None, None
        for stream in self.streams.values():
            with self.lock:
                audio = np.concatenate(stream.pending) if stream.pending else np.zeros(0, np.float32)
            new = len(audio) - stream.last_draft_length
            if new >= DRAFT_MIN_NEW_SECONDS * RATE and rms(audio) > SILENCE_LEVEL:
                if best is None or new > len(best_audio) - best.last_draft_length:
                    best, best_audio = stream, audio
        if best is None:
            return
        best.last_draft_length = len(best_audio)
        try:
            segments, _ = self.whisper(best_audio, beam_size=1)
            self.on_draft(self.label(best.key), " ".join(s.text.strip() for s in segments if s.text.strip()))
        except Exception:
            pass  # a draft is only a preview

    def whisper(self, audio: np.ndarray, beam_size: int, word_timestamps: bool = False):
        context = getattr(self, "context", "")[-CONTEXT_CHARS:] if CONTEXT_CHARS else None
        return self.model.transcribe(
            audio, language=None if self.multilingual else self.language,
            multilingual=self.multilingual, vad_filter=True, beam_size=beam_size,
            hotwords=None if context else self.hotwords, initial_prompt=context or None,
            condition_on_previous_text=False, word_timestamps=word_timestamps)

    def transcribe_final(self, key: str, offset: float, audio: np.ndarray) -> None:
        split_voices = self.voices is not None and key == self.voice_stream and LIVE_SPLIT_PAUSE > 0
        segments, info = self.whisper(audio, beam_size=5, word_timestamps=split_voices)
        for segment in segments:
            text = self.segment_filter.clean(segment.text.strip()) if segment.text.strip() else None
            if not text:
                continue
            if self.language is None and not self.multilingual:
                self.language = info.language  # detected once, then kept for the whole meeting
                self.on_info(f"Language: {info.language}")
            # Whisper may put two people's turns into one phrase; with voices told apart, the
            # phrase is cut where its words pause, and every part gets its own voice.
            parts = [(segment.start, segment.end, text)]
            if split_voices and segment.words and text == segment.text.strip():
                parts, run = [], [segment.words[0]]
                for word in segment.words[1:]:
                    if word.start - run[-1].end >= LIVE_SPLIT_PAUSE:
                        parts.append((run[0].start, run[-1].end, "".join(w.word for w in run).strip()))
                        run = []
                    run.append(word)
                parts.append((run[0].start, run[-1].end, "".join(w.word for w in run).strip()))
            for part_start, part_end, part_text in parts:
                if not part_text:
                    continue
                start, end = offset + part_start, offset + part_end
                voice = None
                if self.voices is not None and key == self.voice_stream:
                    try:
                        voice = self.voices.voice_of(audio[int(part_start * RATE):int(part_end * RATE)])
                    except Exception:
                        voice = self.voices.previous
                self.waiting.append((start, end, key, part_text, voice))
                if key == "computer":
                    self.recent_computer.append((start, end, words(part_text)))

    def remove_echo(self, start: float, end: float, text: str) -> str | None:
        """Takes out of a microphone phrase the words the computer played at the same time
        (heard from loudspeakers). Whisper may join echo and your own words into one phrase, so
        only matching runs are removed; your own runs of 3+ words stay. None: all of it was echo."""
        found = list(re.finditer(r"\w+", text))
        mine = [m.group().casefold() for m in found]
        heard = [w for s, e, ws in self.recent_computer if s <= end + 2.0 and e >= start - 2.0 for w in ws]
        if not mine or not heard:
            return text
        matcher = difflib.SequenceMatcher(None, mine, heard, autojunk=False)
        echoed = set()
        for block in matcher.get_matching_blocks():
            if block.size >= ECHO_MIN_RUN:  # single common words ("the", "you") are not echo
                echoed.update(range(block.a, block.a + block.size))
        if len(echoed) < ECHO_MIN_RUN:
            return text
        kept, run = [], []
        for index in range(len(mine) + 1):
            if index < len(mine) and index not in echoed:
                run.append(index)
                continue
            if len(run) >= ECHO_MIN_RUN:
                kept.append(text[found[run[0]].start():found[run[-1]].end()])
            run = []
        if len(echoed) / len(mine) >= ECHO_SIMILARITY and not kept:
            return None
        return " … ".join(kept) if kept else None

    def write_ready(self, final: bool = False) -> None:
        """Writes, in time order, the segments that no stream can still precede."""
        limit = float("inf") if final else min(s.done_until for s in self.streams.values())
        # In order of start; a segment still open (it ends after what every stream has finished)
        # holds back the later ones, so a long phrase of one side is not written after a short
        # reply of the other that started later.
        self.waiting.sort(key=lambda s: s[0])
        ready = []
        while self.waiting and self.waiting[0][1] <= limit:
            ready.append(self.waiting.pop(0))
        for start, end, key, text, voice in ready:
            if key == "mic" and "computer" in self.streams:
                cleaned = self.remove_echo(start, end, text)
                if cleaned != text:
                    self.echoes += 1
                if not cleaned:
                    continue
                text = cleaned
            label = self.label(key, voice)
            self.paragraphs.add(start, end, text, label)
            self.txt_file.flush()
            self.on_final(start, end, label, text)


# --- shared helpers for the front ends ------------------------------------------------------------

def load_whisper(args, report):
    if os.path.isdir(args.model):
        os.environ["HF_HUB_OFFLINE"] = "1"
    tool.add_cuda_dll_dirs()
    try:
        model = tool.load_model(args.model, "cpu" if args.cpu else "cuda")
    except Exception as error:  # no GPU
        report(f"GPU not usable ({error}); using the CPU, the text will lag behind more.")
        model = tool.load_model(args.model, "cpu")
    hotwords = None
    if not args.no_terms:
        terms, files = tool.load_terms(args.terms + tool.DEFAULT_TERMS_FILES)
        if terms:
            hotwords = ", ".join(terms)
            tool.report_terms(model, hotwords, terms, files)
    return model, hotwords


def run(args) -> int:
    """Live mode: the window, or with --console the plain console version."""
    try:
        import soundcard  # noqa: F401
    except ImportError:
        print("The audio capture package is missing. Run setup.cmd.", file=sys.stderr)
        return 3
    if not args.console:
        import live_gui
        return live_gui.run(args)
    return run_console(args)


def run_console(args) -> int:
    report = lambda line: print(line, flush=True)
    if args.ask and args.language is None:
        choice = tool.ask("Язык встречи:",
                          [f"{n} - {name}" for n, (_, name) in enumerate(tool.LANGUAGE_CHOICES, start=1)],
                          "не знаю, определить по первым фразам", tool.number_in(1, len(tool.LANGUAGE_CHOICES)))
        args.language = tool.LANGUAGE_CHOICES[choice - 1][0] if choice else None
    folder = args.out_dir or new_folder()
    model, hotwords = load_whisper(args, report)
    _, microphone, speakers = list_devices()
    session = LiveSession(
        model, folder, args.language, hotwords, microphone, speakers,
        on_final=lambda start, end, label, text: report(
            f"[{tool.format_clock(start)}] {label + ': ' if label else ''}{text}"),
        on_mic_silent=lambda silent: silent and report(
            "!!! The other side is heard, but your microphone has been silent for a while."),
        on_info=report)
    report("\nListening to:")
    for source in session.sources:
        report(f"  {source.name}")
    report(f"Saving to: {folder}")
    print("\n=== Идёт запись и расшифровка. Нажмите Enter, чтобы остановить. ===\n", flush=True)
    session.start()
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass
    print("Stopping; writing the last sentences...", flush=True)
    session.stop()
    report(f"\nRecorded {tool.format_clock(session.seconds)}.")
    report(f"  live text: {session.txt_path}")
    report(f"  sound:     {session.wav_path}")
    if session.echoes:
        report(f"  {session.echoes} phrases of the other side heard by the microphone were left out as echo")
    filtered = session.segment_filter.report()
    if filtered:
        report(filtered)
    wav_path, txt_path = session.wav_path, session.txt_path
    del session, model
    gc.collect()
    return after_meeting(args, wav_path, txt_path)


def after_meeting(args, wav_path: str, txt_path: str) -> int:
    """Console: offers the full processing of the recording, or a summary of the live text."""
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
