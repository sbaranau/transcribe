"""AI check of a transcript with speaker labels.

The AI does not rewrite the transcript. It returns findings (check_prompt.md), and this module
applies them:

- names: "Говорящий 2" becomes "Анна" where the transcript makes the name clear, or "Анна (?)"
  where it is only likely;
- fixes: a quoted piece of a paragraph and the label of the person who really said it. The quote
  must be found word for word in that paragraph, otherwise the fix is dropped, so the text itself
  cannot change. Afterwards, neighbouring pieces with the same speaker are joined when the first
  one does not end a sentence, which repairs sentences cut between two labels.

The result goes to <name>.checked.txt; <name>.txt stays as the machine made it.
"""
import json
import os
import re

import ai_engines

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
CHECK_PROMPT_FILE = os.path.join(TOOL_DIR, "check_prompt.md")
PARAGRAPH = re.compile(r"^\[(\d\d:\d\d:\d\d)\] ([^:\n\[\]]{1,40}?): (.*)$", re.S)
SENTENCE_ENDINGS = (".", "?", "!", "…")
# Claude and ChatGPT read a whole 3-hour transcript (about 100,000 characters) at once.
CLOUD_CHUNK_CHARS = 200000


class Paragraph:
    def __init__(self, time: str, label: str | None, text: str, origin: int):
        self.time, self.label, self.text, self.origin = time, label, text, origin


def parse(transcript: str) -> list[Paragraph]:
    paragraphs = []
    for number, block in enumerate(p.strip() for p in transcript.split("\n\n")):
        if not block:
            continue
        match = PARAGRAPH.match(block)
        if match:
            paragraphs.append(Paragraph(match[1], match[2], match[3].strip(), number))
        else:
            paragraphs.append(Paragraph("", None, block, number))
    return paragraphs


def has_labels(transcript: str) -> bool:
    return any(p.label for p in parse(transcript))


def parse_json(raw: str) -> dict:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("the AI returned no JSON")
    return json.loads(raw[start:end + 1])


def split_into_parts(paragraphs: list[Paragraph], size: int) -> list[str]:
    parts, current = [], ""
    for p in paragraphs:
        line = f"[{p.time}] {p.label}: {p.text}" if p.label else p.text
        if current and len(current) + len(line) > size:
            parts.append(current)
            current = ""
        current += line + "\n\n"
    if current:
        parts.append(current)
    return parts


def ask_ai(engine: str, location: str, paragraphs: list[Paragraph], report) -> tuple[list, list]:
    prompt = open(CHECK_PROMPT_FILE, encoding="utf-8").read()
    size = CLOUD_CHUNK_CHARS if engine != "local" else ai_engines.local_chunk_chars()
    parts = split_into_parts(paragraphs, size)
    names, fixes = [], []
    for number, part in enumerate(parts, start=1):
        if len(parts) > 1:
            report(f"  checking part {number}/{len(parts)}...")
        data = parse_json(ai_engines.run_single(engine, location, prompt, part))
        names += [n for n in data.get("names", []) if isinstance(n, dict)]
        fixes += [f for f in data.get("fixes", []) if isinstance(f, dict)]
    return names, fixes


def choose_names(names: list[dict], labels: set[str]) -> dict[str, str]:
    """Label -> name to show. A sure name wins over an unsure one; a name claimed for two labels
    is not used, since it would merge two people."""
    best = {}
    for entry in names:
        label, name = str(entry.get("label", "")), str(entry.get("name", "")).strip()
        if label not in labels or not name or len(name) > 40:
            continue
        sure = entry.get("sure") is True
        if label not in best or (sure and not best[label][1]):
            best[label] = (name, sure)
    taken = {}
    for label, (name, _) in best.items():
        taken.setdefault(name.casefold(), []).append(label)
    return {label: (name if sure else f"{name} (?)") for label, (name, sure) in best.items()
            if len(taken[name.casefold()]) == 1}


def find(text: str, quote: str) -> tuple[int, int] | None:
    """Start and end of quote in text: exact, else with any whitespace between the words."""
    position = text.find(quote)
    if position >= 0:
        return position, position + len(quote)
    words = quote.split()
    if not words:
        return None
    match = re.search(r"\s+".join(map(re.escape, words)), text)
    return (match.start(), match.end()) if match else None


def apply(paragraphs: list[Paragraph], names: list[dict], fixes: list[dict]) -> tuple[list[Paragraph], dict]:
    labels = {p.label for p in paragraphs if p.label}
    # Each paragraph becomes a list of pieces [text, label] that fixes can split.
    pieces = [[[p.text, p.label]] for p in paragraphs]
    applied = not_found = 0
    for fix in fixes:
        time, quote, speaker = str(fix.get("at", "")), str(fix.get("text", "")).strip(), str(fix.get("speaker", ""))
        if speaker not in labels or not quote:
            not_found += 1
            continue
        done = False
        for index, p in enumerate(paragraphs):
            if p.time != time or not p.label:
                continue
            for piece_index, (text, label) in enumerate(pieces[index]):
                span = find(text, quote)
                if span is None:
                    continue
                before, middle, after = text[:span[0]].strip(), text[span[0]:span[1]], text[span[1]:].strip()
                replacement = ([[before, label]] if before else []) + [[middle, speaker]] + (
                    [[after, label]] if after else [])
                pieces[index][piece_index:piece_index + 1] = replacement
                done = True
                break
            if done:
                break
        if done:
            applied += 1
        else:
            not_found += 1

    flat = [Paragraph(p.time, label, text, p.origin)
            for p, parts in zip(paragraphs, pieces) for text, label in parts]
    joined = []
    for p in flat:
        previous = joined[-1] if joined else None
        if (previous and p.label and previous.label == p.label
                and (previous.origin == p.origin or not previous.text.rstrip().endswith(SENTENCE_ENDINGS))):
            previous.text = f"{previous.text} {p.text}"
        else:
            joined.append(Paragraph(p.time, p.label, p.text, p.origin))

    shown = choose_names(names, labels)
    for p in joined:
        if p.label in shown:
            p.label = shown[p.label]
    return joined, {"names": shown, "applied": applied, "not_found": not_found,
                    "joined": len(flat) - len(joined)}


def check_file(txt_path: str, engine: str, location: str, force: bool, report=print) -> str | None:
    """Writes <name>.checked.txt and returns its path; None if there is nothing to check."""
    checked_path = os.path.splitext(txt_path)[0] + ".checked.txt"
    if os.path.exists(checked_path) and not force:
        report(f"Checked text exists, kept: {checked_path} (--force redoes it)")
        return checked_path
    transcript = open(txt_path, encoding="utf-8").read()
    paragraphs = [p for p in parse(transcript) if p.label or not p.text.startswith("# ")]
    if not any(p.label for p in paragraphs):
        report("No speaker labels in the transcript, so there is nothing to check "
               "(the check needs speaker separation).")
        return None
    report(f"Checking the text with {ai_engines.describe(engine, location)}: names and "
           f"speaker borders...")
    names, fixes = ask_ai(engine, location, paragraphs, report)
    result, stats = apply(paragraphs, names, fixes)
    named = ", ".join(f"{label} = {name}" for label, name in stats["names"].items()) or "none"
    summary = (f"names: {named}; {stats['applied']} pieces given to another speaker "
               f"({stats['not_found']} suggestions not found in the text and skipped); "
               f"{stats['joined']} cut sentences and paragraphs joined")
    header = (f"# Checked with {ai_engines.title(engine)}: {summary}. "
              f"The machine transcript without these changes: {os.path.basename(txt_path)}")
    with open(checked_path, "w", encoding="utf-8") as out:
        out.write(header + "\n\n")
        for p in result:
            out.write((f"[{p.time}] {p.label}: {p.text}" if p.label else p.text) + "\n\n")
    report(f"Check done: {summary}")
    report(f"  {checked_path}")
    return checked_path
