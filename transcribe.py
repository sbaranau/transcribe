"""Transcribe meeting recordings to readable text, optionally with a Claude summary.

Usage:
    transcribe.cmd <file> [<file> ...] [--language ru] [--summary] [--srt] [--out-dir DIR] [--cpu] [--force]

For each audio/video input it writes, into a subfolder named <name> next to the input, or into --out-dir:
    <name>.txt          full transcript in paragraphs, each starting with [hh:mm:ss]
    <name>.srt          subtitles with exact segment timings (with --srt)
    <name>.summary.md   structured summary made by Claude Code (with --summary)

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
--terms FILE and from terms.txt in the tool folder (local, not in git). They are passed to Whisper as hotwords for every 30-second window.
"""
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import time

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = os.path.join(TOOL_DIR, "models", "large-v3-turbo")
SUMMARY_PROMPT_FILE = os.path.join(TOOL_DIR, "summary_prompt.md")
# Most specific first: when the list is too long, Whisper drops the terms at the end.
DEFAULT_TERMS_FILES = [os.path.join(TOOL_DIR, "terms.txt")]
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


def add_cuda_dll_dirs() -> None:
    """Make the pip-installed NVIDIA DLLs (cuBLAS, cuDNN) visible on Windows."""
    nvidia_dir = os.path.join(sys.prefix, "Lib", "site-packages", "nvidia")
    for bin_dir in glob.glob(os.path.join(nvidia_dir, "*", "bin")):
        os.add_dll_directory(bin_dir)
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


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
    """Joins short Whisper segments into readable paragraphs with a start timestamp."""

    def __init__(self, out):
        self.out = out
        self.texts = []
        self.start = 0.0
        self.last_end = 0.0

    def add(self, start: float, end: float, text: str) -> None:
        if self.texts:
            duration = start - self.start
            sentence_ended = self.texts[-1].endswith(SENTENCE_ENDINGS)
            if (start - self.last_end >= PARAGRAPH_PAUSE_SECONDS
                    or (duration >= PARAGRAPH_SOFT_LIMIT_SECONDS and sentence_ended)
                    or duration >= PARAGRAPH_HARD_LIMIT_SECONDS):
                self.flush()
        if not self.texts:
            self.start = start
        self.texts.append(text)
        self.last_end = end

    def flush(self) -> None:
        if self.texts:
            self.out.write(f"[{format_clock(self.start)}] {' '.join(self.texts)}\n\n")
            self.out.flush()
            self.texts = []


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


def split_on_pauses(segment, text: str) -> list[tuple[float, float, str]]:
    """Splits a segment where its words are separated by a pause, so each piece carries the
    times of what is actually said. Whisper often puts words from both sides of a long pause
    into one segment, which would start a subtitle or paragraph minutes too early.
    A segment whose text the filter changed is kept whole, timed by its first and last word."""
    words = segment.words or []
    if not words:
        return [(segment.start, segment.end, text)]
    if text != segment.text.strip():
        return [(words[0].start, words[-1].end, text)]
    pieces, current = [], [words[0]]
    for word in words[1:]:
        if word.start - current[-1].end >= WORD_PAUSE_SECONDS:
            pieces.append(current)
            current = []
        current.append(word)
    pieces.append(current)
    result = []
    for piece in pieces:
        piece_text = "".join(word.word for word in piece).strip()
        if piece_text:
            result.append((piece[0].start, piece[-1].end, piece_text))
    return result or [(words[0].start, words[-1].end, text)]


def transcribe_file(model, path: str, args) -> str:
    started = time.time()
    segments, info = model.transcribe(
        path,
        language=args.language,
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
    print(f"Language: {info.language} (p={info.language_probability:.2f}), "
          f"duration {format_clock(info.duration)}", flush=True)

    base = output_base(path, args.out_dir)
    os.makedirs(os.path.dirname(base), exist_ok=True)
    txt_path = base + ".txt"
    srt_path = base + ".srt"
    # Written under a temporary name and renamed at the end: an interrupted run must not
    # leave a half transcript that the next run would take as done.
    txt_partial = txt_path + PARTIAL_SUFFIX
    srt_partial = srt_path + PARTIAL_SUFFIX
    srt_file = open(srt_partial, "w", encoding="utf-8") if args.srt else None
    last_report = 0.0
    segment_filter = None if args.no_filter else SegmentFilter()
    kept = 0
    completed = False
    try:
        with open(txt_partial, "w", encoding="utf-8") as txt_file:
            paragraphs = ParagraphWriter(txt_file)
            for segment in segments:
                text = segment.text.strip()
                if text and segment_filter:
                    text = segment_filter.clean(text)
                if not text:
                    continue
                for start, end, piece in split_on_pauses(segment, text):
                    kept += 1
                    paragraphs.add(start, end, piece)
                    if srt_file:
                        srt_file.write(f"{kept}\n{format_srt_time(start)} --> "
                                       f"{format_srt_time(end)}\n{piece}\n\n")
                if segment.end - last_report >= 300:
                    last_report = segment.end
                    percent = 100 * segment.end / info.duration if info.duration else 0
                    print(f"  {format_clock(segment.end)} / {format_clock(info.duration)} "
                          f"({percent:.0f}%), elapsed {format_clock(time.time() - started)}",
                          flush=True)
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


def find_claude() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    fallback = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
    return fallback if os.path.isfile(fallback) else None


def summarize(txt_path: str, args) -> bool:
    summary_path = os.path.splitext(txt_path)[0] + ".summary.md"
    if os.path.exists(summary_path) and not args.force:
        print(f"Summary exists, kept: {summary_path} (--force redoes it)", flush=True)
        return True
    claude = find_claude()
    if not claude:
        print("Claude Code CLI (claude) not found; skipping the summary.", file=sys.stderr)
        return False

    with open(SUMMARY_PROMPT_FILE, encoding="utf-8") as prompt_file:
        prompt = prompt_file.read()
    with open(txt_path, encoding="utf-8") as transcript_file:
        transcript = transcript_file.read()

    print("Sending the transcript to Claude for the summary (your account; "
          "your Claude usage rules apply)...", flush=True)
    started = time.time()
    # Uses the Claude Code login of whoever runs the tool. The flags keep that person's own
    # setup out of the call: no tools, no MCP servers, no user settings or hooks, and no saved
    # session holding the transcript.
    result = subprocess.run(
        [claude, "-p", prompt,
         "--tools", "",
         "--strict-mcp-config",
         "--setting-sources", "project",
         "--no-session-persistence"],
        input=transcript,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=TOOL_DIR,
    )
    if result.returncode != 0 or not result.stdout.strip():
        print(f"Summary FAILED (exit {result.returncode}): {result.stderr.strip()}", file=sys.stderr)
        return False

    title = os.path.splitext(os.path.basename(txt_path))[0]
    with open(summary_path, "w", encoding="utf-8") as summary_file:
        summary_file.write(f"<!-- Summary of {title}.txt, made by Claude; check it against the transcript. -->\n\n")
        summary_file.write(result.stdout.strip() + "\n")
    print(f"Summary done in {format_clock(time.time() - started)}: {summary_path}", flush=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline speech-to-text for meeting recordings.")
    parser.add_argument("inputs", nargs="+",
                        help="audio/video files (mp4, mkv, mp3, wav, m4a, ...) or existing .txt transcripts")
    parser.add_argument("--language", default=None,
                        help="spoken language, e.g. ru, de, en; omit to auto-detect from the first 30s")
    parser.add_argument("--summary", action="store_true",
                        help="also write <name>.summary.md via Claude Code (sends the transcript to Claude)")
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
    args = parser.parse_args()

    missing = [p for p in args.inputs + args.terms if not os.path.isfile(p)]
    for path in missing:
        print(f"File not found: {path}", file=sys.stderr)
    if missing:
        return 2

    media = [p for p in args.inputs if not p.lower().endswith(".txt")]
    transcripts = [p for p in args.inputs if p.lower().endswith(".txt")]
    if transcripts and not args.summary:
        print("A .txt input is only summarized; add --summary.", file=sys.stderr)
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
        if args.summary:
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
        elif args.summary and not summarize(txt_path, args):
            failures += 1

    for path in transcripts:
        print(f"\n{path}", flush=True)
        if not summarize(path, args):
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
