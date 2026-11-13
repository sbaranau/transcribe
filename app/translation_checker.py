"""AI check of a machine translation of a transcript (translator.py).

The AI gets each paragraph of the original next to its translation and returns pinpoint fixes
(translation_check_prompt.md): words quoted from a paragraph of the translation and the words to
put instead. A fix is applied only if its quote is found word for word in that paragraph of the
translation, and only if the replacement is of a plausible size, so the AI cannot rewrite or
drop the translation. The result goes to <name>.<language>.checked.txt; the translation as the
machine made it stays next to it.
"""
import os

import ai_engines
import checker
from translator import HEADER

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(TOOL_DIR, "translation_check_prompt.md")
# Original and translation together; Claude and ChatGPT read a 3-hour meeting at once.
CLOUD_CHUNK_CHARS = 300000


def blocks(text: str) -> list[str]:
    return [b.strip() for b in text.split("\n\n") if b.strip()]


def split_prefix(paragraph: str) -> tuple[str, str]:
    """("[hh:mm:ss] Label: ", text) of a transcript paragraph; ("", paragraph) without one."""
    match = HEADER.match(paragraph)
    return (match.group(1), match.group(2)) if match else ("", paragraph)


def split_into_parts(pairs: list[tuple[int, str, str]], size: int) -> list[str]:
    parts, current = [], ""
    for number, original, translation in pairs:
        prefix, original_text = split_prefix(original)
        entry = (f"[{number}] {prefix.strip()}\nORIGINAL: {original_text}\n"
                 f"TRANSLATION: {split_prefix(translation)[1]}\n\n")
        if current and len(current) + len(entry) > size:
            parts.append(current)
            current = ""
        current += entry
    return parts + ([current] if current else [])


def apply(translation: list[str], fixes: list[dict]) -> tuple[list[str], int, int]:
    result = list(translation)
    applied = skipped = 0
    for fix in fixes:
        try:
            index = int(fix.get("paragraph"))
        except (TypeError, ValueError):
            skipped += 1
            continue
        wrong, right = str(fix.get("wrong", "")).strip(), str(fix.get("right", "")).strip()
        if not (0 <= index < len(result)) or not wrong or not right or wrong == right:
            skipped += 1
            continue
        if len(right) > 3 * len(wrong) + 80:  # a fix, not a rewrite
            skipped += 1
            continue
        # The "[hh:mm:ss] Label:" prefix is not the AI's to change.
        prefix, text = split_prefix(result[index])
        span = checker.find(text, wrong)
        if span is None:
            skipped += 1
            continue
        result[index] = prefix + text[:span[0]] + right + text[span[1]:]
        applied += 1
    return result, applied, skipped


def check_file(original_path: str, translation_path: str, engine: str, location: str, force: bool,
               report=print) -> str:
    """Writes <translation>.checked.txt next to the translation and returns its path."""
    checked_path = os.path.splitext(translation_path)[0] + ".checked.txt"
    if os.path.exists(checked_path) and not force:
        report(f"Checked translation exists, kept: {checked_path} (--force redoes it)")
        return checked_path
    original = blocks(open(original_path, encoding="utf-8").read())
    translation = blocks(open(translation_path, encoding="utf-8").read())
    if len(original) != len(translation):
        raise ValueError(f"{os.path.basename(translation_path)} does not match "
                         f"{os.path.basename(original_path)} paragraph by paragraph")
    pairs = [(n, o, t) for n, (o, t) in enumerate(zip(original, translation)) if not o.startswith("# ")]
    report(f"Checking the translation with {ai_engines.describe(engine, location)}...")
    prompt = open(PROMPT_FILE, encoding="utf-8").read()
    size = CLOUD_CHUNK_CHARS if engine != "local" else ai_engines.local_chunk_chars()
    parts = split_into_parts(pairs, size)
    fixes = []
    for number, part in enumerate(parts, start=1):
        if len(parts) > 1:
            report(f"  checking part {number}/{len(parts)}...")
        data = checker.parse_json(ai_engines.run_single(engine, location, prompt, part))
        fixes += [f for f in data.get("fixes", []) if isinstance(f, dict)]
    result, applied, skipped = apply(translation, fixes)
    summary = f"{applied} places corrected ({skipped} suggestions not found in the translation or too large, skipped)"
    header = (f"# Translation checked with {ai_engines.title(engine)}: {summary}. "
              f"The machine translation without these changes: {os.path.basename(translation_path)}")
    with open(checked_path, "w", encoding="utf-8") as out:
        out.write(header + "\n\n" + "\n\n".join(b for b in result if not b.startswith("# ")) + "\n")
    report(f"Translation check done: {summary}")
    report(f"  {checked_path}")
    return checked_path
