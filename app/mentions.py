"""Finding where the person using the app is named or addressed in the meeting.

The person types how they are called ("Сергей, Серёжа, Sergey, Baranov"); each name is also
found in its Russian case forms (Сергея, Сергею, Сергеем, Сергее; Анны, Анне, Анну, Анной), as
a whole word, ignoring case and ё/е. Only the other side's words are checked: when you say your
own name, nobody is addressing you.
"""
import re

# Case endings that follow the stem, by how the name ends (nominative).
ENDINGS = [
    ("ия", 2, ["ия", "ии", "ию", "ией", "иею"]),             # Мария, Наталия
    ("ья", 2, ["ья", "ьи", "ье", "ью", "ьей", "ьею"]),       # Наталья, Дарья
    ("ей", 1, ["й", "я", "ю", "ем", "е"]),                    # Сергей, Алексей, Андрей
    ("ий", 2, ["ий", "ия", "ию", "ием", "ии"]),               # Дмитрий, Юрий
    ("й", 1, ["й", "я", "ю", "ем", "е"]),                     # Николай
    ("а", 1, ["а", "ы", "и", "е", "у", "ой", "ою", "ей"]),    # Анна, Ольга, Саша
    ("я", 1, ["я", "и", "е", "ю", "ей", "ею"]),               # Катя, Таня
    ("ь", 1, ["ь", "я", "ю", "ем", "е", "и", "ью"]),          # Игорь, Любовь
]
CONSONANT_ENDINGS = ["", "а", "у", "ом", "е", "ым", "ой", "ых"]  # Иван, Петров, Баранов
CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)


def names_from(entered: str) -> list[str]:
    """The names typed into the field, separated by commas or semicolons."""
    return [name.strip() for name in re.split(r"[,;\n]+", entered or "") if len(name.strip()) >= 2]


def _letters(text: str) -> str:
    """A regular expression for the letters of text, with е and ё matching each other."""
    return "".join("[её]" if c in "её" else re.escape(c) for c in text.lower())


def name_pattern(name: str) -> str:
    """The regular expression for one name with its case forms (Latin names as typed, plus 's)."""
    name = name.strip()
    lower = name.lower()
    if " " in lower:  # "Сергей Баранов": the whole phrase, each word in its case forms
        return r"\s+".join(name_pattern(part) for part in lower.split())
    if not CYRILLIC.search(lower):
        return _letters(lower) + r"(?:'s)?"
    for ending, cut, forms in ENDINGS:
        if lower.endswith(ending) and len(lower) - cut >= 2:
            stem = lower[:-cut]
            return _letters(stem) + "(?:" + "|".join(_letters(form) for form in forms) + ")"
    if lower[-1] in "бвгджзклмнпрстфхцчшщ":
        return _letters(lower) + "(?:" + "|".join(_letters(form) for form in CONSONANT_ENDINGS) + ")"
    return _letters(lower)


class Matcher:
    """Finds the names in a text. Empty (finds nothing) without names."""

    def __init__(self, entered: str):
        self.names = names_from(entered)
        alternatives = sorted((name_pattern(name) for name in self.names), key=len, reverse=True)
        self.regex = (re.compile(r"(?<!\w)(?:" + "|".join(alternatives) + r")(?!\w)", re.IGNORECASE)
                      if alternatives else None)

    def __bool__(self) -> bool:
        return self.regex is not None

    def spans(self, text: str) -> list[tuple[int, int]]:
        """(start, end) of each mention in text."""
        return [match.span() for match in self.regex.finditer(text)] if self.regex else []


def write_list(path: str, mentions: list[tuple[float, str | None, str]], names: list[str], clock) -> None:
    """mentions.txt: when, who said it, and the whole paragraph."""
    with open(path, "w", encoding="utf-8") as out:
        out.write(f"Mentions of: {', '.join(names)}\n\n")
        for seconds, label, text in mentions:
            out.write(f"[{clock(seconds)}] {label + ': ' if label else ''}{text}\n\n")
