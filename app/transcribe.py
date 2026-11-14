"""Transcribe meeting recordings to readable text, optionally with an AI check and summary.

Usage:
    app\\transcribe.cmd <file> [<file> ...] [--language ru|multi] [--speakers [N]] [--check]
                        [--summary] [--ai claude|codex|local] [--srt] [--out-dir DIR] [--cpu] [--force]
    app\\transcribe.cmd <file> --ask   asks the questions instead (what drop-files-here.cmd does)

For each audio/video input it writes, into a subfolder named <name> next to the input, or into --out-dir:
    <name>.txt          full transcript in paragraphs, each starting with [hh:mm:ss] and, with
                        --speakers, the speaker label
    <name>.srt          subtitles timed by the spoken words (with --srt)
    <name>.summary.md   structured summary made by an AI (with --summary): Claude Code, ChatGPT
                        through the Codex CLI, or a local model server (see ai_engines.py)
    <name>.<lang>.txt   local machine translation into en, de or ru (with --translate, see
                        translator.py); <name>.<lang>.checked.txt with --check-translation

Transcription runs locally (NVIDIA GPU when available, CPU otherwise); nothing leaves the
machine. Only --summary sends the transcript to Claude, under your own account, so use it only
for content your Claude usage rules (your organization's, Anthropic's terms) allow.
A .txt input is not transcribed again: with --summary it is only summarized, and the
summary is written next to that .txt.

Existing results are kept: a recording whose <name>.txt exists is not transcribed again (with
--summary only the missing summary is made), and an existing summary is not redone. --force
overwrites them. The transcript is written to a .partial file first, so an interrupted run
leaves no incomplete <name>.txt behind.

Terms (names, products, jargon) that Whisper should spell right are read, one per line, from
--terms FILE and from terms.txt in the tool folder, next to README.md (local, not in git). They
are passed to Whisper as hotwords for every 30-second window.
"""
import argparse
import bisect
import glob
import os
import re
import sys
import threading
import time
import wave

import numpy as np

import ai_engines
import checker
import screenshots
import translation_checker
import translator
import ui_text
from ui_text import t

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))  # app\: code, prompts, models
ROOT_DIR = os.path.dirname(TOOL_DIR)  # the folder people open: scripts, guides, terms.txt
DEFAULT_MODEL = os.path.join(TOOL_DIR, "models", "large-v3-turbo")
SUMMARY_PROMPT_FILE = os.path.join(TOOL_DIR, "summary_prompt.md")
# Most specific first: when the list is too long, Whisper drops the terms at the end.
DEFAULT_TERMS_FILES = [os.path.join(ROOT_DIR, "terms.txt")]
# faster-whisper keeps at most max_length // 2 - 1 = 223 hotword tokens and silently drops the rest.
HOTWORDS_TOKEN_LIMIT = 223

# A new paragraph starts after a pause this long, or once a paragraph is long enough
# and the previous segment ended a sentence. Whisper stretches segment ends over short
# pauses, so the length rule does most of the work and keeps a timestamp every ~30s.
PARAGRAPH_PAUSE_SECONDS = 2.0
PARAGRAPH_SOFT_LIMIT_SECONDS = 30.0
PARAGRAPH_HARD_LIMIT_SECONDS = 90.0
SENTENCE_ENDINGS = (".", "?", "!", "…")
# A segment is split where two words are this far apart (see split_on_pauses).
WORD_PAUSE_SECONDS = 1.0

# Phrases Whisper invents in silence or noise, learned from subtitled videos. A segment is
# dropped only when it is short and contains one of them, so real speech is kept.
INVENTED_PHRASES = re.compile(
    r"субтитры (?:сделал|создавал|подготовил|делал)|редактор субтитров|dimatorzok"
    r"|продолжение следует|спасибо за просмотр|подписывайтесь на (?:наш )?канал"
    r"|thanks? (?:you )?for watching|untertitel (?:im auftrag|der amara|von)|amara\.org"
    r"|vielen dank fürs zuschauen",
    re.IGNORECASE)
INVENTED_PHRASE_MAX_WORDS = 12
# The same phrase four or more times in a row inside one segment is a decoding loop.
REPEAT_LOOP = re.compile(r"(\b\w.{0,60}?)(?:[\s,.;:!?-]+\1\b){3,}", re.IGNORECASE)
# A segment that repeats the previous one word for word is dropped from this length on;
# short ones ("Да.", "OK.") are often said twice for real.
REPEATED_SEGMENT_MIN_WORDS = 3

PARTIAL_SUFFIX = ".partial"
MULTILINGUAL = "multi"

# Voice separation (speaker diarization) with sherpa-onnx; models downloaded by the setup.
SAMPLE_RATE = 16000
DIARIZATION_DIR = os.path.join(TOOL_DIR, "models", "diarization")
SEGMENTATION_MODEL = os.path.join(DIARIZATION_DIR, "sherpa-onnx-pyannote-segmentation-3-0", "model.onnx")
EMBEDDING_MODEL = os.path.join(DIARIZATION_DIR, "nemo_en_titanet_small.onnx")
# Clustering distance when the number of speakers is unknown: higher merges more voices.
# Chosen 2026-11-12 on the sherpa-onnx reference recordings (one with 4 speakers, three with
# 2): TitaNet-small counted all four right from 0.8 to 0.9; WeSpeaker ResNet34, CAM++ and
# ERes2Net got at most 3 of 4 at any threshold.
SPEAKER_THRESHOLD = 0.85
# Voice groups whose average embeddings (from up to CENTROID_SECONDS of their speech) are at
# least this alike are taken as one person. On a real 3-hour recording with 4 people, sherpa-onnx
# gave 80 groups; joining at 0.70-0.75 left exactly 4 persons with more than 2% of the speech
# (60, 19, 10, 8%), and on the reference recordings no two different people were joined at any
# value from 0.55 to 0.8 (different people there: 0.12-0.43).
SAME_PERSON_SIMILARITY = 0.72
CENTROID_SECONDS = 30.0
PERSON_CENTROID_SECONDS = 60.0
# Voice check inside long turns, see check_voice_inside_turns().
INSIDE_MIN_TURN = 3.0
INSIDE_WINDOW = 1.5
INSIDE_HOP = 0.75
INSIDE_MARGIN = 0.2
# Persons with less of the speech than this after joining are fragments and are folded into the
# most alike larger person.
MIN_SPEAKER_SHARE = 0.02
# Segmentation windows (10 s) advance by this share of their length. sherpa-onnx's default
# 0.1 took ~28 min per 3 h of audio; 0.25 counted the same speakers on the reference
# recordings in ~11 min, 0.75 started to miss.
WINDOW_SHIFT_RATIO = 0.25
# Calls recorded by the live mode: (you, the other side as a whole, one person of the other side).
STREAM_LABELS = {"ru": ("Вы", "Собеседники", "Собеседник"), "en": ("You", "Others", "Speaker"),
                 "de": ("Sie", "Andere", "Sprecher"), "fr": ("Vous", "Autres", "Intervenant"),
                 "uk": ("Ви", "Співрозмовники", "Співрозмовник")}
# In such a call, a word is yours when the microphone channel is this many times louder than the
# computer channel (6 dB); echo of the other side in the microphone is quieter than the original.
CALL_CHANNEL_MARGIN = 2.0
# ... and carries real speech: the live mode brings your voice to about -20 dB, while microphone
# background noise could otherwise win over a quiet moment of the other side.
CALL_MIC_MIN_LEVEL = 0.01  # -40 dB
SPEAKER_LABELS = {"ru": "Говорящий", "uk": "Мовець", "de": "Sprecher", "fr": "Intervenant",
                  "it": "Parlante", "es": "Hablante"}


# What to run when something installed by the setup is missing.
SETUP_HINT = (r"windows\setup.cmd" if os.name == "nt" else
              "macos/setup.command" if sys.platform == "darwin" else "linux/setup.sh")


def add_cuda_dll_dirs() -> None:
    """Make the pip-installed NVIDIA DLLs (cuBLAS, cuDNN) visible on Windows. On Linux,
    linux/transcribe.sh puts their lib folders on LD_LIBRARY_PATH before Python starts."""
    if os.name != "nt":
        return
    nvidia_dir = os.path.join(sys.prefix, "Lib", "site-packages", "nvidia")
    for bin_dir in glob.glob(os.path.join(nvidia_dir, "*", "bin")):
        os.add_dll_directory(bin_dir)
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


def open_path(path: str) -> None:
    """Opens a file or folder with the program the desktop has for it."""
    if os.name == "nt":
        os.startfile(path)
    else:
        import subprocess
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def format_clock(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def format_srt_time(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


class ParagraphWriter:
    """Joins short Whisper segments into readable paragraphs with a start timestamp and,
    when speakers are known, the speaker label; a new speaker always starts a paragraph."""

    def __init__(self, out):
        self.out = out
        self.texts = []
        self.start = 0.0
        self.last_end = 0.0
        self.speaker = None

    def add(self, start: float, end: float, text: str, speaker: str | None = None) -> None:
        if self.texts:
            duration = start - self.start
            sentence_ended = self.texts[-1].endswith(SENTENCE_ENDINGS)
            if (speaker != self.speaker
                    or start - self.last_end >= PARAGRAPH_PAUSE_SECONDS
                    or (duration >= PARAGRAPH_SOFT_LIMIT_SECONDS and sentence_ended)
                    or duration >= PARAGRAPH_HARD_LIMIT_SECONDS):
                self.flush()
        if not self.texts:
            self.start = start
            self.speaker = speaker
        self.texts.append(text)
        self.last_end = end

    def flush(self) -> None:
        if self.texts:
            label = f"{self.speaker}: " if self.speaker else ""
            self.out.write(f"[{format_clock(self.start)}] {label}{' '.join(self.texts)}\n\n")
            self.out.flush()
            self.texts = []


class SpeakerTimeline:
    """Speaker turns from the diarization, looked up for words in time order. Speakers are
    numbered by their first appearance in the transcript and labelled in the meeting's
    language, e.g. "Говорящий 2"."""

    def __init__(self, turns: list[tuple[float, float, int]], label: str):
        self.turns = sorted(turns)
        self.label = label
        self.next_turn = 0
        self.active = []
        self.numbers = {}
        self.previous = None

    def speaker_of(self, start: float, end: float) -> str:
        """The speaker who talks most during [start, end]; words in no turn keep the
        previous speaker. Calls must come in time order."""
        while self.next_turn < len(self.turns) and self.turns[self.next_turn][0] <= end:
            self.active.append(self.turns[self.next_turn])
            self.next_turn += 1
        self.active = [turn for turn in self.active if turn[1] >= start]
        best, best_overlap = None, 0.0
        for turn_start, turn_end, speaker in self.active:
            overlap = min(end, turn_end) - max(start, turn_start)
            if overlap > best_overlap:
                best, best_overlap = speaker, overlap
        if best is None:
            best = self.previous if self.previous is not None else (
                self.turns[0][2] if self.turns else 0)
        self.previous = best
        if best not in self.numbers:
            self.numbers[best] = len(self.numbers) + 1
        return f"{self.label} {self.numbers[best]}"


class SegmentFilter:
    """Removes typical Whisper hallucinations: invented closing phrases, decoding loops
    inside a segment, and a segment repeated word for word."""

    def __init__(self):
        self.previous = None
        self.invented = 0
        self.repeated = 0
        self.loops = 0

    def clean(self, text: str) -> str | None:
        """Returns the text to keep, or None to drop the segment."""
        collapsed = REPEAT_LOOP.sub(r"\1", text)
        if collapsed != text:
            self.loops += 1
            text = collapsed
        normalized = re.sub(r"[\W_]+", " ", text.casefold()).strip()
        if not normalized:
            return None
        words = len(normalized.split())
        if words <= INVENTED_PHRASE_MAX_WORDS and INVENTED_PHRASES.search(text):
            self.invented += 1
            return None
        if normalized == self.previous and words >= REPEATED_SEGMENT_MIN_WORDS:
            self.repeated += 1
            return None
        self.previous = normalized
        return text

    def report(self) -> str | None:
        if not (self.invented or self.repeated or self.loops):
            return None
        return (f"Filtered: {self.invented} invented phrases, {self.repeated} repeated segments "
                f"dropped; {self.loops} loops collapsed")


def load_terms(paths: list[str]) -> tuple[list[str], list[str]]:
    """Reads terms, one per line ('#' starts a comment); returns (terms, files actually read)."""
    terms, used_files, seen = [], [], set()
    for path in paths:
        if not os.path.isfile(path):
            continue
        used_files.append(os.path.basename(path))
        with open(path, encoding="utf-8-sig") as terms_file:
            for line in terms_file:
                term = line.split("#", 1)[0].strip()
                if term and term.casefold() not in seen:
                    seen.add(term.casefold())
                    terms.append(term)
    return terms, used_files


def report_terms(model, hotwords: str, terms: list[str], files: list[str]) -> None:
    try:
        token_count = len(model.hf_tokenizer.encode(" " + hotwords, add_special_tokens=False).ids)
    except Exception:  # tokenizer API differs; the count is only informative
        token_count = None
    size = f", {token_count} tokens" if token_count is not None else ""
    print(f"Terms: {len(terms)} from {', '.join(files)}{size}", flush=True)
    if token_count is not None and token_count > HOTWORDS_TOKEN_LIMIT:
        print(f"WARNING: terms exceed Whisper's limit of {HOTWORDS_TOKEN_LIMIT} tokens; "
              f"the terms at the end are ignored. Shorten the list.", flush=True)


def load_model(model_ref: str, device: str):
    from faster_whisper import WhisperModel

    compute_type = "float16" if device == "cuda" else "int8"
    started = time.time()
    model = WhisperModel(model_ref, device=device, compute_type=compute_type)
    print(f"Model loaded on {device.upper()} in {time.time() - started:.0f}s", flush=True)
    return model


def output_base(path: str, out_dir: str | None) -> str:
    """Returns the output path without extension: <out_dir>/<name>, or by default
    <recording folder>/<name>/<name>, so each recording gets its own subfolder."""
    name = os.path.splitext(os.path.basename(path))[0]
    directory = out_dir or os.path.join(os.path.dirname(os.path.abspath(path)), name)
    return os.path.join(directory, name)


def split_segment(segment, text: str, speakers: SpeakerTimeline | None
                  ) -> list[tuple[float, float, str, str | None]]:
    """Splits a segment where its words are separated by a pause or the speaker changes, so
    each piece carries the times of what is actually said and one speaker. Whisper often puts
    words from both sides of a long pause, or from two people, into one segment.
    Returns (start, end, text, speaker label or None).
    A segment whose text the filter changed is kept whole, timed by its first and last word."""
    words = segment.words or []
    if not words:
        speaker = speakers.speaker_of(segment.start, segment.end) if speakers else None
        return [(segment.start, segment.end, text, speaker)]
    if text != segment.text.strip():
        start, end = words[0].start, words[-1].end
        return [(start, end, text, speakers.speaker_of(start, end) if speakers else None)]
    pieces, current, current_speaker = [], [], None
    for word in words:
        speaker = speakers.speaker_of(word.start, word.end) if speakers else None
        if current and (word.start - current[-1].end >= WORD_PAUSE_SECONDS
                        or speaker != current_speaker):
            pieces.append((current, current_speaker))
            current = []
        if not current:
            current_speaker = speaker
        current.append(word)
    pieces.append((current, current_speaker))
    result = []
    for piece, speaker in pieces:
        piece_text = "".join(word.word for word in piece).strip()
        if piece_text:
            result.append((piece[0].start, piece[-1].end, piece_text, speaker))
    return result or [(words[0].start, words[-1].end, text, current_speaker)]


def diarize(audio, num_speakers: int) -> list[tuple[float, float, int]]:
    """Finds who speaks when, on the CPU. num_speakers 0 means: estimate the number.

    1. sherpa-onnx (pyannote segmentation + NeMo TitaNet voice embeddings) splits the speech
       into voice groups with a low threshold, so one person often ends up in many groups.
    2. refine_speakers() joins groups whose average voice embeddings are alike, folds tiny
       groups into the closest person and, when the number of speakers is given, joins the
       most alike persons until that number is left. sherpa-onnx's own fixed-count mode is not
       used: on a 4-person recording it merged two people and kept a 0.4% noise group."""
    import sherpa_onnx

    threads = max(1, (os.cpu_count() or 2) // 2)  # leave CPU for Whisper running alongside
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=SEGMENTATION_MODEL, window_shift_ratio=WINDOW_SHIFT_RATIO),
            num_threads=threads),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=EMBEDDING_MODEL, num_threads=threads),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=SPEAKER_THRESHOLD),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    diarization = sherpa_onnx.OfflineSpeakerDiarization(config)
    started = time.time()
    reported = [0]

    def progress(done: int, total: int) -> int:
        percent = 100 * done // max(total, 1)
        if percent >= reported[0] + 20:
            reported[0] = percent - percent % 20
            print(f"  voices {percent}%, elapsed {format_clock(time.time() - started)}", flush=True)
        return 0

    result = diarization.process(audio, callback=progress).sort_by_start_time()
    turns = [(turn.start, turn.end, turn.speaker) for turn in result]
    groups = len({speaker for _, _, speaker in turns})
    turns = refine_speakers(audio, turns, num_speakers, threads)
    print(f"Speakers: {len({speaker for _, _, speaker in turns})} (from {groups} voice groups), "
          f"found in {format_clock(time.time() - started)}", flush=True)
    return turns


def refine_speakers(audio, turns: list[tuple[float, float, int]], num_speakers: int,
                    threads: int) -> list[tuple[float, float, int]]:
    """Joins voice groups that belong to one person; see diarize()."""
    import numpy as np
    import sherpa_onnx

    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=EMBEDDING_MODEL, num_threads=threads))

    def embed(start: float, end: float):
        stream = extractor.create_stream()
        stream.accept_waveform(SAMPLE_RATE, audio[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)])
        stream.input_finished()
        vector = np.array(extractor.compute(stream))
        return vector / np.linalg.norm(vector)

    talk = {}
    for start, end, speaker in turns:
        talk[speaker] = talk.get(speaker, 0.0) + end - start
    total = sum(talk.values()) or 1.0
    # Average voice embedding of each group, from its longest turns (each cut to 10 s).
    centroids = {}
    for group in talk:
        vectors, used = [], 0.0
        for start, end, _ in sorted((t for t in turns if t[2] == group), key=lambda t: t[0] - t[1]):
            if end - start < 1.0 or used >= CENTROID_SECONDS:
                break
            end = min(end, start + 10.0)
            vectors.append(embed(start, end))
            used += end - start
        if vectors:
            centroid = np.mean(vectors, axis=0)
            centroids[group] = centroid / np.linalg.norm(centroid)

    # Persons: lists of groups with their speech time and average embedding.
    persons = {group: ([group], talk[group], centroids[group]) for group in centroids}

    def join_most_alike(stop_below: float | None) -> bool:
        keys = list(persons)
        best, pair = -2.0, None
        for i, first in enumerate(keys):
            for second in keys[i + 1:]:
                similarity = float(persons[first][2] @ persons[second][2])
                if similarity > best:
                    best, pair = similarity, (first, second)
        if pair is None or (stop_below is not None and best < stop_below):
            return False
        first, second = pair
        groups_a, time_a, vector_a = persons.pop(first)
        groups_b, time_b, vector_b = persons.pop(second)
        vector = vector_a * time_a + vector_b * time_b
        persons[first] = (groups_a + groups_b, time_a + time_b, vector / np.linalg.norm(vector))
        return True

    while join_most_alike(SAME_PERSON_SIMILARITY):
        pass
    # Tiny groups are fragments: they go to the most alike larger person. When the number of
    # speakers is given, that many of the most talkative persons are kept even if small, so
    # someone who joined late or said little is not folded into another voice.
    large = {key for key, (_, seconds, _) in persons.items() if seconds / total >= MIN_SPEAKER_SHARE}
    if num_speakers > 0:
        large |= set(sorted(persons, key=lambda key: persons[key][1], reverse=True)[:num_speakers])
    if large:
        for key in [key for key in persons if key not in large]:
            groups, seconds, vector = persons.pop(key)
            target = max(large, key=lambda other: float(persons[other][2] @ vector))
            target_groups, target_seconds, target_vector = persons[target]
            persons[target] = (target_groups + groups, target_seconds + seconds, target_vector)
    if num_speakers > 0:
        while len(persons) > num_speakers and join_most_alike(None):
            pass

    person_of = {group: key for key, (groups, _, _) in persons.items() for group in groups}
    # Groups without an embedding (only very short turns) take the person speaking nearest in time.
    known = [turn for turn in turns if turn[2] in person_of]
    starts = [turn[0] for turn in known]
    result = []
    for start, end, group in turns:
        if group in person_of:
            result.append((start, end, person_of[group]))
        elif known:
            index = bisect.bisect_left(starts, start)
            nearest = min(known[max(0, index - 1):index + 1],
                          key=lambda turn: max(turn[0] - end, start - turn[1], 0.0))
            result.append((start, end, person_of[nearest[2]]))
        else:
            result.append((start, end, group))
    return check_voice_inside_turns(result, embed)


def check_voice_inside_turns(turns: list[tuple[float, float, int]], embed
                             ) -> list[tuple[float, float, int]]:
    """Short interjections inside someone else's long turn ("wait, how many?") are often not
    split off by the segmentation. Inside every turn longer than INSIDE_MIN_TURN seconds, the
    voice is checked every INSIDE_HOP seconds over INSIDE_WINDOW seconds; a stretch that is
    clearly (INSIDE_MARGIN) more alike another person goes to that person.
    Measured on three AMI meetings (4 people each, reference speaker timing): words in turns
    under 2 s went from 82% to 89% right with the number of speakers given, all words stayed
    at 98%."""
    import numpy as np

    centroids = {}
    for person in {speaker for _, _, speaker in turns}:
        vectors, used = [], 0.0
        for start, end, _ in sorted((t for t in turns if t[2] == person), key=lambda t: t[0] - t[1]):
            if end - start < 1.0 or used >= PERSON_CENTROID_SECONDS:
                break
            end = min(end, start + 10.0)
            vectors.append(embed(start, end))
            used += end - start
        if vectors:
            centroid = np.mean(vectors, axis=0)
            centroids[person] = centroid / np.linalg.norm(centroid)
    if len(centroids) < 2:
        return turns

    result = []
    for start, end, speaker in turns:
        pieces = [(start, end, speaker)]
        if end - start >= INSIDE_MIN_TURN and speaker in centroids:
            pieces, position = [], start
            while position < end:
                step_end = min(end, position + INSIDE_HOP)
                window_start = max(start, (position + step_end) / 2 - INSIDE_WINDOW / 2)
                vector = embed(window_start, min(end, window_start + INSIDE_WINDOW))
                best = max(centroids, key=lambda person: float(centroids[person] @ vector))
                clearly_other = float(centroids[best] @ vector) - float(centroids[speaker] @ vector)
                pieces.append((position, step_end, best if clearly_other > INSIDE_MARGIN else speaker))
                position = step_end
        for piece in pieces:
            if result and result[-1][2] == piece[2] and abs(result[-1][1] - piece[0]) < 1e-6:
                result[-1] = (result[-1][0], piece[1], piece[2])
            else:
                result.append(piece)
    return result


def speaker_label(language: str | None) -> str:
    return SPEAKER_LABELS.get(language or "", "Speaker")


def call_recording(path: str) -> bool:
    """A recording made by the live mode: two channels (left: your microphone after its gain,
    right: the computer sound, i.e. the other side), with meeting.live.txt next to it."""
    if not path.lower().endswith(".wav"):
        return False
    if not os.path.isfile(os.path.join(os.path.dirname(os.path.abspath(path)), "meeting.live.txt")):
        return False
    try:
        with wave.open(path) as recording:
            return recording.getnchannels() == 2
    except (OSError, wave.Error):
        return False


class ChannelSpeakers:
    """Labels for a call recorded by the live mode. Who said a word is known from the channels:
    words clearly louder in the microphone channel are yours ("Вы"); the other words belong to
    the other side, told apart by voice when the computer channel was separated ("Собеседник 2"),
    or named as a whole ("Собеседники")."""

    def __init__(self, microphone, computer, others: "SpeakerTimeline | None", language: str | None):
        self.microphone, self.computer, self.others = microphone, computer, others
        self.mine, self.other_side, _ = STREAM_LABELS.get(language or "", ("You", "Others", "Speaker"))

    def speaker_of(self, start: float, end: float) -> str:
        first = int(start * SAMPLE_RATE)
        last = max(int(end * SAMPLE_RATE), first + 1)
        mine = float(np.sqrt(np.mean(np.square(self.microphone[first:last]))))
        theirs = float(np.sqrt(np.mean(np.square(self.computer[first:last]))))
        if mine >= CALL_MIC_MIN_LEVEL and mine > CALL_CHANNEL_MARGIN * theirs:
            return self.mine
        return self.others.speaker_of(start, end) if self.others else self.other_side


def transcribe_file(model, path: str, args) -> str:
    from faster_whisper import decode_audio

    started = time.time()
    # Decoded once and shared: the voice separation needs the same 16 kHz samples.
    call = call_recording(path)
    if call:
        # Live-mode call: Whisper hears both sides together; who spoke comes from the channels, and
        # only the other side's channel is separated by voice (the count given includes you).
        microphone, computer = decode_audio(path, sampling_rate=SAMPLE_RATE, split_stereo=True)
        audio = (microphone + computer) / 2
        separate_audio = computer
        count_of_voices = (args.speakers - 1 if args.speakers >= 2 else 0) if args.speakers is not None else None
        print("Call recorded by the live mode: your words are told by the microphone channel.", flush=True)
    else:
        audio = decode_audio(path, sampling_rate=SAMPLE_RATE)
        separate_audio, count_of_voices = audio, args.speakers
    # The voice separation runs on the CPU in a thread while Whisper runs (on the GPU), so it
    # adds little time; its result is needed only when the text is written.
    voices = {}
    voice_thread = None
    if count_of_voices is not None:
        count = f"{count_of_voices} speakers" if count_of_voices else "number of speakers unknown"
        side = " of the other side" if call else ""
        print(f"Separating voices{side} ({count}) on the CPU, alongside the transcription...", flush=True)

        def separate() -> None:
            try:
                voices["turns"] = diarize(separate_audio, count_of_voices)
            except Exception as error:  # reported after the transcription
                voices["error"] = error

        voice_thread = threading.Thread(target=separate, daemon=True)
        voice_thread.start()
    multilingual = args.language == MULTILINGUAL
    segments, info = model.transcribe(
        audio,
        language=None if multilingual else args.language,
        # With several languages, the language is detected again for every 30-second window.
        multilingual=multilingual,
        vad_filter=True,
        beam_size=5,
        hotwords=args.hotwords,
        # Feeding each window the previous text makes one misrecognition or loop spread over
        # the following minutes; hotwords are still passed to every window.
        condition_on_previous_text=False,
        # Segment times come from the first and last spoken word: without this, a segment
        # next to a long pause can start minutes before its words are said.
        word_timestamps=True,
    )
    language_note = ", several languages" if multilingual else ""
    print(f"Language: {info.language} (p={info.language_probability:.2f}){language_note}, "
          f"duration {format_clock(info.duration)}", flush=True)

    segment_filter = None if args.no_filter else SegmentFilter()
    recognized = []  # (segment, text after the filter)
    last_report = 0.0
    for segment in segments:
        text = segment.text.strip()
        if text and segment_filter:
            text = segment_filter.clean(text)
        if text:
            recognized.append((segment, text))
        if segment.end - last_report >= 300:
            last_report = segment.end
            percent = 100 * segment.end / info.duration if info.duration else 0
            print(f"  {format_clock(segment.end)} / {format_clock(info.duration)} "
                  f"({percent:.0f}%), elapsed {format_clock(time.time() - started)}", flush=True)

    speakers = None
    if voice_thread:
        if voice_thread.is_alive():
            print("Waiting for the voice separation to finish...", flush=True)
        voice_thread.join()
        if "error" in voices:
            raise RuntimeError(f"voice separation failed: {voices['error']}")
        if call:
            one_of_others = STREAM_LABELS.get(info.language or "", ("You", "Others", "Speaker"))[2]
            speakers = SpeakerTimeline(voices["turns"], one_of_others)
        else:
            speakers = SpeakerTimeline(voices["turns"], speaker_label(info.language))
    if call:
        speakers = ChannelSpeakers(microphone, computer, speakers, info.language)

    base = output_base(path, args.out_dir)
    os.makedirs(os.path.dirname(base), exist_ok=True)
    txt_path = base + ".txt"
    srt_path = base + ".srt"
    # Written under a temporary name and renamed at the end: an interrupted run must not
    # leave a half transcript that the next run would take as done.
    txt_partial = txt_path + PARTIAL_SUFFIX
    srt_partial = srt_path + PARTIAL_SUFFIX
    srt_file = open(srt_partial, "w", encoding="utf-8") if args.srt else None
    kept = 0
    completed = False
    try:
        with open(txt_partial, "w", encoding="utf-8") as txt_file:
            paragraphs = ParagraphWriter(txt_file)
            for segment, text in recognized:
                for start, end, piece, speaker in split_segment(segment, text, speakers):
                    kept += 1
                    paragraphs.add(start, end, piece, speaker)
                    if srt_file:
                        label = f"{speaker}: " if speaker else ""
                        srt_file.write(f"{kept}\n{format_srt_time(start)} --> "
                                       f"{format_srt_time(end)}\n{label}{piece}\n\n")
            paragraphs.flush()
        completed = True
    finally:
        if srt_file:
            srt_file.close()
        if not completed:
            for partial in (txt_partial, srt_partial):
                if os.path.exists(partial):
                    os.remove(partial)
    os.replace(txt_partial, txt_path)
    if args.srt:
        os.replace(srt_partial, srt_path)

    report = segment_filter.report() if segment_filter else None
    if report:
        print(report, flush=True)
    print(f"Transcript done in {format_clock(time.time() - started)}: {txt_path}", flush=True)
    return txt_path


def summarize(txt_path: str, args, summary_path: str | None = None) -> bool:
    summary_path = summary_path or os.path.splitext(txt_path)[0] + ".summary.md"
    if os.path.exists(summary_path) and not args.force:
        print(f"Summary exists, kept: {summary_path} (--force redoes it)", flush=True)
        return True
    engine, location = args.ai_engine, args.ai_location
    with open(SUMMARY_PROMPT_FILE, encoding="utf-8") as prompt_file:
        prompt = prompt_file.read()
    with open(txt_path, encoding="utf-8") as transcript_file:
        transcript = transcript_file.read()

    where = ("stays on this computer" if engine == "local"
             else "goes to it under your account; your usage rules apply")
    print(f"Summary with {ai_engines.describe(engine, location)}; the transcript {where}...", flush=True)
    started = time.time()
    try:
        text = ai_engines.run(engine, location, prompt, transcript,
                              report=lambda line: print(line, flush=True))
    except Exception as error:  # the AI tool failed or is not logged in
        print(f"Summary FAILED: {error}", file=sys.stderr)
        return False

    with open(summary_path, "w", encoding="utf-8") as summary_file:
        summary_file.write(f"<!-- Summary of {os.path.basename(txt_path)}, made by {ai_engines.title(engine)}; "
                           f"check it against the transcript. -->\n\n")
        summary_file.write(text + "\n")
    print(f"Summary done in {format_clock(time.time() - started)}: {summary_path}", flush=True)
    return True


def choose_ai(args, interactive: bool) -> bool:
    """Sets args.ai_engine and args.ai_location. Asks when interactive; otherwise takes --ai or
    the first installed one. Returns False if there is none (the check and the summary are
    then skipped)."""
    if interactive:
        print(t("ai.searching_console"), flush=True)
    else:
        print("Looking for the installed AI tools and checking their login...", flush=True)
    started = time.time()
    found, left_out = ai_engines.verify_engines(ai_engines.find_engines())
    for engine, reason in left_out.items():
        print("  " + t("ai.installed_but", title=ai_engines.title(engine), reason=reason) if interactive
              else f"  {ai_engines.title(engine)} left out: {reason}", flush=True)
    if interactive:
        names = ", ".join(ai_engines.describe(engine, found[engine]) for engine in found) or t("ai.nothing")
        print(t("ai.ready", seconds=f"{time.time() - started:.0f}", names=names), flush=True)
    if args.ai:
        if args.ai in found:
            args.ai_engine, args.ai_location = args.ai, found[args.ai]
            return True
        print(f"--ai {args.ai}: not found on this computer.", file=sys.stderr)
        if not interactive:
            return False
    if found and not interactive:
        args.ai_engine, args.ai_location = next(iter(found.items()))
        return True
    if found:
        engines = list(found)
        choice = ask(t("ai.which"),
                     [f"{n} - {ai_engines.describe(e, found[e])}" for n, e in enumerate(engines, start=1)],
                     ai_engines.title(engines[0]), number_in(1, len(engines)))
        engine = engines[(choice or 1) - 1]
        args.ai_engine, args.ai_location = engine, found[engine]
        return True
    if not interactive:
        print("No AI found (Claude Code, Codex, or a local model server); the check and the "
              "summary are skipped.", file=sys.stderr)
        return False
    print(t("ai.none_found"))
    while True:
        choice = ask(t("ai.what_now"), [t("ai.option_skip"), t("ai.option_path")], t("ai.skip"),
                     number_in(1, 2))
        if choice != 2:
            return False
        print(t("ai.path_prompt"))
        try:
            entered = input("> ").lstrip("﻿")
        except EOFError:
            return False
        result = ai_engines.classify(entered)
        if result:
            usable, left_out = ai_engines.verify_engines(dict([result]))
            if not usable:
                print(t("ai.found_but", reason=left_out[result[0]]))
                continue
            args.ai_engine, args.ai_location = result
            ai_engines.remember(*result)
            print(t("ai.found_saved", name=ai_engines.describe(*result)))
            return True
        print(t("ai.path_wrong"))


def ask(question: str, options: list[str], enter_means: str, accept) -> object:
    """Asks a numbered question in the console until the answer is valid. An empty answer
    (or no console at all) returns None, the default named by enter_means."""
    print(f"\n{question}")
    for line in options:
        print(f"  {line}")
    print(f"  Enter - {enter_means}")
    while True:
        try:
            answer = input(t("your_choice")).strip().lstrip("﻿")
        except EOFError:
            print()
            return None
        if not answer:
            return None
        value = accept(answer)
        if value is not None:
            return value
        print(t("not_understood"))


def yes_no() -> list[str]:
    return [f"1 - {t('yes')}", f"2 - {t('no')}"]


def number_in(low: int, high: int):
    def accept(answer: str):
        return int(answer) if answer.isdigit() and low <= int(answer) <= high else None
    return accept


def ask_for_files() -> list[str]:
    print(t("drop_files"))
    try:
        line = input("> ").lstrip("﻿")
    except EOFError:
        return []
    # Explorer pastes dragged paths separated by spaces, quoted when they contain spaces.
    return [quoted or plain for quoted, plain in re.findall(r'"([^"]+)"|(\S+)', line)]


def ask_options(args, has_media: bool) -> None:
    """Fills in, by numbered questions, every choice not already given as an option."""
    if has_media and args.language is None:
        choices = ui_text.meeting_languages()
        choice = ask(t("ask.language"),
                     [f"{number} - {name}" for number, (_, name) in enumerate(choices, start=1)],
                     t("ask.detect"), number_in(1, len(choices)))
        args.language = choices[choice - 1][0] if choice else None
    if has_media and args.speakers is None:
        choice = ask(t("ask.split"), yes_no(), t("no"), number_in(1, 2))
        if choice == 1:
            count = ask(t("ask.count"), [t("ask.count_option")], t("ask.detect"), number_in(1, 20))
            args.speakers = count or 0
    labelled = args.speakers is not None if has_media else args.labelled_input
    if labelled and not args.check:
        choice = ask(t("ask.check"), yes_no(), t("no"), number_in(1, 2))
        args.check = choice == 1
    if not args.summary:
        choice = ask(t("ask.summary"), yes_no(), t("no"), number_in(1, 2))
        args.summary = choice == 1
    if not args.translate:
        source = args.language if args.language in translator.LANGUAGES else None
        targets = [code for code in ui_text.meeting_languages()[:3] if code[0] != source]
        choice = ask(t("ask.translate"), [f"{n} - {name}" for n, (_, name) in enumerate(targets, start=1)],
                     t("no"), number_in(1, len(targets)))
        args.translate = targets[choice - 1][0] if choice else None
    if args.translate and not args.check_translation:
        choice = ask(t("ask.check_translation"), yes_no(), t("no"), number_in(1, 2))
        args.check_translation = choice == 1
    if args.check or args.summary or args.check_translation:
        print(t("ask.ai_rules"))
        if not choose_ai(args, interactive=True):
            args.check = args.summary = args.check_translation = False
    print()


def after_transcript(txt_path: str, args) -> bool:
    """The optional AI steps for a finished transcript: the check, then the summary (made from
    the checked text when there is one). Returns False if a step failed."""
    source, ok = txt_path, True
    if args.check and not txt_path.endswith(".checked.txt"):
        try:
            checked = checker.check_file(txt_path, args.ai_engine, args.ai_location, args.force,
                                         report=lambda line: print(line, flush=True))
            source = checked or txt_path
        except Exception as error:  # the AI failed or returned something unusable
            print(f"Check FAILED: {error}", file=sys.stderr, flush=True)
            ok = False
    base = txt_path[:-len(".checked.txt")] if txt_path.endswith(".checked.txt") else os.path.splitext(txt_path)[0]
    if args.translate:
        ok = translate(source, base, args) and ok
    if args.summary:
        ok = summarize(source, args, base + ".summary.md") and ok
    # Screenshots taken during the live mode (screenshots/ next to the recording): the texts
    # again as Markdown, with each screenshot after its paragraph.
    variants = [base + ".txt", base + ".checked.txt"]
    variants += [f"{base}.{code}{end}" for code in translator.LANGUAGES for end in (".txt", ".checked.txt")]
    screenshots.write_markdown_for(variants, report=lambda line: print(line, flush=True))
    return ok


def translate(source: str, base: str, args) -> bool:
    """<base>.<lang>.txt, made locally from the (checked) transcript; then, if asked, its AI
    check into <base>.<lang>.checked.txt."""
    target = args.translate
    out_path = f"{base}.{target}.txt"
    try:
        if os.path.exists(out_path) and not args.force:
            print(f"Translation exists, kept: {out_path} (--force redoes it)", flush=True)
        else:
            language = args.language if args.language in translator.LANGUAGES else None
            text = open(source, encoding="utf-8").read()
            language = language or translator.detect(text[:20000])
            if language not in translator.LANGUAGES:
                print("Translation skipped: the transcript is not in English, German or Russian.", flush=True)
                return True
            if language == target:
                print(f"Translation skipped: the transcript is already in {target}.", flush=True)
                return True
            print(f"Translating {language} -> {target} locally (Opus-MT)...", flush=True)
            started = time.time()
            translator.translate_file(source, target, out_path, language,
                                      report=lambda line: print(line, flush=True))
            print(f"Translation done in {format_clock(time.time() - started)}: {out_path}", flush=True)
        if args.check_translation:
            translation_checker.check_file(source, out_path, args.ai_engine, args.ai_location, args.force,
                                           report=lambda line: print(line, flush=True))
        return True
    except Exception as error:
        print(f"Translation FAILED: {error}", file=sys.stderr, flush=True)
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline speech-to-text for meeting recordings.")
    parser.add_argument("--live", action="store_true",
                        help="transcribe a meeting while it happens, from the computer's sound and "
                             "the microphone, in a window (live-transcribe)")
    parser.add_argument("--ui-language", choices=list(ui_text.LANGUAGES), default=None,
                        help="language of the questions and the window: en, de or ru (remembered; "
                             "default: the one chosen last, else the system's)")
    parser.add_argument("--console", action="store_true",
                        help="with --live: no window, text in the console, Enter stops it")
    parser.add_argument("inputs", nargs="*",
                        help="audio/video files (mp4, mkv, mp3, wav, m4a, ...) or existing .txt "
                             "transcripts; without any, the tool asks for them")
    parser.add_argument("--ask", action="store_true",
                        help="ask in the console for language, speakers and summary (what is not "
                             "given as an option); used by drop-files-here")
    parser.add_argument("--language", default=None,
                        help="spoken language, e.g. ru, de, en, or 'multi' for several languages; "
                             "omit to auto-detect from the first 30s")
    parser.add_argument("--speakers", nargs="?", type=int, const=0, default=None, metavar="N",
                        help="label who speaks (voice separation); N = number of speakers if known")
    parser.add_argument("--check", action="store_true",
                        help="with speaker labels: have an AI put in names and fix text with the "
                             "wrong speaker, into <name>.checked.txt (sends the transcript to it, "
                             "unless it is a local model)")
    parser.add_argument("--summary", action="store_true",
                        help="also write <name>.summary.md with an AI (sends the transcript to it, "
                             "unless it is a local model); made from the checked text if there is one")
    parser.add_argument("--ai", choices=ai_engines.ENGINES, default=None,
                        help="AI for the check and the summary: claude (Claude Code), codex (ChatGPT "
                             "via Codex CLI) or local (Ollama, LM Studio, ...); default: the first installed")
    parser.add_argument("--translate", choices=list(translator.LANGUAGES), default=None,
                        help="also translate the transcript locally into en, de or ru (Opus-MT, "
                             "nothing leaves the computer): <name>.<lang>.txt")
    parser.add_argument("--check-translation", action="store_true",
                        help="with --translate: have an AI correct clear mistakes of the translation, "
                             "into <name>.<lang>.checked.txt (sends original and translation to it, "
                             "unless it is a local model)")
    parser.add_argument("--srt", action="store_true", help="also write .srt subtitles with exact timings")
    parser.add_argument("--out-dir", default=None, help="output folder (default: a subfolder named after each input, next to it)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="model folder or Whisper model name (default: bundled large-v3-turbo)")
    parser.add_argument("--cpu", action="store_true", help="force CPU even if a GPU is available")
    parser.add_argument("--terms", action="append", default=[], metavar="FILE",
                        help="extra terms file, one term per line; can be given several times "
                             "(terms.txt in the tool folder is always read)")
    parser.add_argument("--no-terms", action="store_true", help="use no terms at all")
    parser.add_argument("--no-filter", action="store_true",
                        help="keep everything Whisper outputs, including likely hallucinations "
                             "(invented closing phrases, loops, repeated segments)")
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing results (by default a recording whose .txt exists "
                             "is not transcribed again, and an existing summary is kept)")
    args = parser.parse_args(argv)
    args.ai_engine = args.ai_location = None
    if args.ui_language:
        ui_text.set_language(args.ui_language)
        if args.ui_language != ui_text.saved_language():
            ui_text.save_language(args.ui_language)
            import shortcuts
            shortcuts.rename_existing()
    if args.live:
        import live
        return live.run(args)

    if not args.inputs:
        if not args.ask:
            parser.print_usage(sys.stderr)
            return 2
        args.inputs = ask_for_files()
        if not args.inputs:
            print("No file given.", file=sys.stderr)
            return 2

    missing = [p for p in args.inputs + args.terms if not os.path.isfile(p)]
    for path in missing:
        print(f"File not found: {path}", file=sys.stderr)
    if missing:
        return 2

    media = [p for p in args.inputs if not p.lower().endswith(".txt")]
    transcripts = [p for p in args.inputs if p.lower().endswith(".txt")]
    args.labelled_input = any(checker.has_labels(open(p, encoding="utf-8").read()) for p in transcripts)
    if args.ask:
        ask_options(args, bool(media))
    elif args.check or args.summary or args.check_translation:
        if not choose_ai(args, interactive=False):
            args.check = args.summary = args.check_translation = False
            if transcripts and not args.translate:
                return 1
    if args.speakers is not None and media and not (
            os.path.isfile(SEGMENTATION_MODEL) and os.path.isfile(EMBEDDING_MODEL)):
        print(f"The voice separation models are missing. Run {SETUP_HINT}.", file=sys.stderr)
        return 3
    if args.check_translation and not args.translate:
        print("--check-translation needs --translate.", file=sys.stderr)
        return 2
    if transcripts and not (args.summary or args.check or args.translate):
        print("A .txt input is only checked, translated or summarized; add --check, --translate or "
              "--summary.", file=sys.stderr)
        return 2

    # Recordings already transcribed are not done again, so a corrected .txt is never lost;
    # with --summary their existing .txt is summarized instead.
    done = []
    if not args.force:
        done = [p for p in media if os.path.isfile(output_base(p, args.out_dir) + ".txt")]
        media = [p for p in media if p not in done]
    for path in done:
        txt_path = output_base(path, args.out_dir) + ".txt"
        print(f"Transcript exists, kept: {txt_path} (--force redoes it)", flush=True)
        if args.srt and not os.path.isfile(output_base(path, args.out_dir) + ".srt"):
            print("  No .srt for it: subtitles are made only together with the transcript; "
                  "use --force to make both.", flush=True)
        if args.summary or args.check or args.translate:
            transcripts.append(txt_path)

    failures = 0
    model = None
    device = "cpu" if args.cpu else "cuda"
    if media:
        if os.path.isdir(args.model):
            os.environ["HF_HUB_OFFLINE"] = "1"
        add_cuda_dll_dirs()
        try:
            model = load_model(args.model, device)
        except Exception as error:  # no GPU, driver or CUDA problem
            if device == "cpu":
                raise
            print(f"GPU not usable ({error}); falling back to CPU, this will be several times slower.",
                  flush=True)
            device = "cpu"
            model = load_model(args.model, device)

    args.hotwords = None
    if media and not args.no_terms:
        terms, terms_files = load_terms(args.terms + DEFAULT_TERMS_FILES)
        if terms:
            args.hotwords = ", ".join(terms)
            report_terms(model, args.hotwords, terms, terms_files)

    for number, path in enumerate(media, start=1):
        print(f"\n[{number}/{len(media)}] {path}", flush=True)
        txt_path = None
        try:
            txt_path = transcribe_file(model, path, args)
        except Exception as error:
            if device == "cuda":
                print(f"GPU run failed ({error}); retrying on CPU.", flush=True)
                device = "cpu"
                model = load_model(args.model, device)
                try:
                    txt_path = transcribe_file(model, path, args)
                except Exception as cpu_error:
                    print(f"FAILED: {cpu_error}", file=sys.stderr, flush=True)
            else:
                print(f"FAILED: {error}", file=sys.stderr, flush=True)
        if txt_path is None:
            failures += 1
        elif not after_transcript(txt_path, args):
            failures += 1

    for path in transcripts:
        print(f"\n{path}", flush=True)
        if not after_transcript(path, args):
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
