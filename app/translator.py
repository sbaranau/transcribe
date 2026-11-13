"""Local translation between English, German and Russian with the Opus-MT models of the
University of Helsinki (Helsinki-NLP, https://github.com/Helsinki-NLP/Opus-MT; CC-BY 4.0 and
Apache 2.0), in the ONNX export of the Xenova/opus-mt-* repositories, run with ONNX Runtime and
the tokenizers package that are already installed. Nothing leaves the computer.

There are models for en<->ru and en<->de; German<->Russian goes through English (two steps).
A model is downloaded the first time its direction is needed (download_models.py --translation
fetches all of them), into app/models/translation/<from>-<to>.

Text is translated sentence by sentence (beam search, as the models were trained); the
transcript's "[hh:mm:ss] Label:" prefixes are kept as they are.
"""
import json
import os
import queue
import re
import threading
import unicodedata

import numpy as np

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(TOOL_DIR, "models", "translation")
LANGUAGES = ("en", "de", "ru")
# Direction -> (repository, pinned revision).
MODELS = {
    ("ru", "en"): ("Xenova/opus-mt-ru-en", "afe8c6c738ec81b6d033fd8f44f9678a639a7c67"),
    ("en", "ru"): ("Xenova/opus-mt-en-ru", "e050376e960175e8ddc5cff85025dc8436cddd68"),
    ("de", "en"): ("Xenova/opus-mt-de-en", "399dfd68706739fffd503f876093e455ae268a06"),
    ("en", "de"): ("Xenova/opus-mt-en-de", "1ca130c44c4c5441ef16d48aae521a424ab644f7"),
}
# "" = the full-precision export; "_quantized" = 8-bit, a quarter of the size (see README).
VARIANT = ""
FILES = ["config.json", "generation_config.json", "tokenizer.json",
         f"onnx/encoder_model{VARIANT}.onnx", f"onnx/decoder_model_merged{VARIANT}.onnx"]
BEAMS = 4
MAX_SENTENCE_TOKENS = 400  # the models take 512; longer pieces are cut at commas or spaces
HEADER = re.compile(r"^(\[\d\d:\d\d:\d\d\]\s+(?:[^:\n\[\]]{1,40}:\s+)?)(.*)$", re.S)


def route(source: str, target: str) -> list[tuple[str, str]]:
    """The model steps from one language to another: direct, or through English."""
    if source == target:
        return []
    if (source, target) in MODELS:
        return [(source, target)]
    return [(source, "en"), ("en", target)]


def folder_of(direction: tuple[str, str]) -> str:
    return os.path.join(MODEL_DIR, "-".join(direction))


def is_downloaded(direction: tuple[str, str]) -> bool:
    return all(os.path.isfile(os.path.join(folder_of(direction), name)) for name in FILES)


def download(direction: tuple[str, str], report=print) -> None:
    from huggingface_hub import hf_hub_download
    repo, revision = MODELS[direction]
    report(f"Downloading the translation model {'-'.join(direction)} (about "
           f"{110 if VARIANT else 440} MB, once)...")
    for name in FILES:
        hf_hub_download(repo, name, revision=revision, local_dir=folder_of(direction))


class MarianOnnx:
    """One Opus-MT (Marian) model: tokenizer, encoder, decoder with cache, beam search."""

    def __init__(self, folder: str):
        import onnxruntime
        from tokenizers import Tokenizer
        config = json.load(open(os.path.join(folder, "config.json"), encoding="utf-8"))
        self.eos = config["eos_token_id"]
        self.pad = config["pad_token_id"]
        self.start = config["decoder_start_token_id"]
        self.layers = config["decoder_layers"]
        self.heads = config["decoder_attention_heads"]
        self.head_size = config["d_model"] // self.heads
        self.tokenizer = Tokenizer.from_str(json.dumps(loadable_tokenizer(os.path.join(folder, "tokenizer.json"))))
        options = onnxruntime.SessionOptions()
        options.log_severity_level = 3
        providers = ["CPUExecutionProvider"]
        self.encoder = onnxruntime.InferenceSession(
            os.path.join(folder, "onnx", f"encoder_model{VARIANT}.onnx"), options, providers=providers)
        self.decoder = onnxruntime.InferenceSession(
            os.path.join(folder, "onnx", f"decoder_model_merged{VARIANT}.onnx"), options, providers=providers)
        self.past_names = [i.name for i in self.decoder.get_inputs() if i.name.startswith("past_key_values")]
        self.present_names = [o.name for o in self.decoder.get_outputs() if o.name.startswith("present")]

    def tokens(self, text: str) -> list[int]:
        # NFKC is the normalization of the models' SentencePiece; see loadable_tokenizer.
        return self.tokenizer.encode(unicodedata.normalize("NFKC", text)).ids

    def translate(self, text: str, beams: int = BEAMS) -> str:
        ids = self.tokens(text)
        if not ids or ids == [self.eos]:
            return ""
        input_ids = np.array([ids], dtype=np.int64)
        mask = np.ones_like(input_ids)
        hidden = self.encoder.run(None, {"input_ids": input_ids, "attention_mask": mask})[0]
        hidden = np.repeat(hidden, beams, axis=0)
        mask = np.repeat(mask, beams, axis=0)
        sequences = [[self.start] for _ in range(beams)]
        scores = np.zeros(beams, dtype=np.float32)
        scores[1:] = -1e9  # all beams start equal; only the first one is expanded at first
        past = {name: np.zeros((beams, self.heads, 0, self.head_size), dtype=np.float32) for name in self.past_names}
        finished = []
        longest = min(512, 2 * len(ids) + 20)
        for step in range(longest):
            feed = {"encoder_attention_mask": mask, "encoder_hidden_states": hidden,
                    "input_ids": np.array([[s[-1]] for s in sequences], dtype=np.int64),
                    "use_cache_branch": np.array([step > 0])}
            feed.update(past)
            outputs = self.decoder.run(None, feed)
            logits = outputs[0][:, -1, :]
            logits[:, self.pad] = -np.inf
            top = logits.max(axis=1, keepdims=True)
            log_probs = logits - (top + np.log(np.exp(logits - top).sum(axis=1, keepdims=True)))
            totals = (scores[:, None] + log_probs).ravel()
            best = np.argpartition(-totals, 2 * beams)[:2 * beams]
            best = best[np.argsort(-totals[best])]
            chosen, new_scores = [], []
            for flat in best:
                beam, token = divmod(int(flat), log_probs.shape[1])
                if token == self.eos:
                    length = len(sequences[beam])  # without the start token, with the end
                    finished.append((totals[flat] / length, sequences[beam][1:]))
                else:
                    chosen.append((beam, token))
                    new_scores.append(totals[flat])
                if len(chosen) == beams:
                    break
            if len(finished) >= beams or not chosen:
                break
            order = np.array([beam for beam, _ in chosen])
            sequences = [sequences[beam] + [token] for beam, token in chosen]
            scores = np.array(new_scores, dtype=np.float32)
            presents = dict(zip(self.present_names, outputs[1:]))
            for name in self.past_names:
                if ".decoder." in name:
                    past[name] = presents[name.replace("past_key_values", "present")][order]
                elif step == 0:
                    # The encoder part is computed at the first step only, the same for every beam,
                    # and passed on unchanged.
                    past[name] = presents[name.replace("past_key_values", "present")]
        if not finished:
            finished = [(scores[0], sequences[0][1:])]
        tokens = max(finished, key=lambda f: f[0])[1]
        text = self.tokenizer.decode(tokens, skip_special_tokens=True).strip()
        # A German date ends in a period ("den 15."), and so does the sentence: "15.." -> "15.".
        return re.sub(r"(?<!\.)\.\.(?!\.)", ".", text)


def loadable_tokenizer(path: str) -> dict:
    """The tokenizer.json of the Xenova exports, made loadable by the tokenizers package: its
    "Precompiled" normalizer has no character map (transformers.js skips it, tokenizers refuses
    it), so it is dropped and the text is NFKC-normalized before encoding instead; older
    Metaspace settings are written the current way."""
    data = json.load(open(path, encoding="utf-8"))
    normalizer = data.get("normalizer") or {}
    if normalizer.get("type") == "Precompiled" and not normalizer.get("precompiled_charsmap"):
        data["normalizer"] = None

    def metaspace(node):
        if isinstance(node, dict):
            if node.get("type") == "Metaspace" and "add_prefix_space" in node:
                node["prepend_scheme"] = "always" if node.pop("add_prefix_space") else "never"
                node.setdefault("split", True)
            for value in node.values():
                metaspace(value)
        elif isinstance(node, list):
            for value in node:
                metaspace(value)

    metaspace(data.get("pre_tokenizer"))
    metaspace(data.get("decoder"))
    return data


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+(?=\S)", text.strip())
    return [p for p in parts if p]


class Translator:
    """Translates from one language to another, loading (and downloading) what the route needs.
    Thread-safe: one translation at a time."""

    def __init__(self, source: str, target: str, report=print):
        self.source, self.target = source, target
        self.models = []
        for direction in route(source, target):
            if not is_downloaded(direction):
                download(direction, report)
            self.models.append(MarianOnnx(folder_of(direction)))
        self.lock = threading.Lock()

    def sentence(self, text: str) -> str:
        for model in self.models:
            pieces = [text]
            if len(model.tokens(text)) > MAX_SENTENCE_TOKENS:
                pieces = cut(text, model, MAX_SENTENCE_TOKENS)
            text = " ".join(model.translate(piece) for piece in pieces)
        return text

    def text(self, text: str) -> str:
        """A paragraph or a phrase: translated sentence by sentence."""
        with self.lock:
            return " ".join(self.sentence(s) for s in split_sentences(text))

    def line(self, line: str) -> str:
        """A transcript line: the "[hh:mm:ss] Label:" prefix stays, the text is translated."""
        if line.startswith("# "):
            return line  # the tool's own header lines (checked text), in English
        match = HEADER.match(line)
        if not match:
            return self.text(line) if line.strip() else line
        return translate_prefix(match.group(1), self.target) + self.text(match.group(2))


# The tool's own speaker labels (transcribe.STREAM_LABELS, SPEAKER_LABELS): you, the other side
# as a whole, one voice of the other side, one speaker of a recording.
LABELS = {"en": ("You", "Others", "Speaker", "Speaker"), "de": ("Sie", "Andere", "Sprecher", "Sprecher"),
          "ru": ("Вы", "Собеседники", "Собеседник", "Говорящий")}


def translate_label(label: str, target: str) -> str:
    """"Говорящий 2" -> "Speaker 2", "Вы" -> "You"; names (from the AI check) stay as they are."""
    number = ""
    word = label
    if label.rsplit(" ", 1)[-1].isdigit():
        word, number = label.rsplit(" ", 1)
        number = " " + number
    # "Speaker 2" is both kinds in English and German; "Говорящий" fits either meaning.
    for kind in (0, 1, 3, 2):
        if any(word == words[kind] for words in LABELS.values()) and (kind >= 2) == bool(number):
            return LABELS[target][kind] + number
    return label


def translate_prefix(prefix: str, target: str) -> str:
    """"[00:01:10] Говорящий 2: " with the label translated."""
    time, _, rest = prefix.partition("] ")
    label = rest.rstrip().rstrip(":")
    if not label:
        return prefix
    return f"{time}] {translate_label(label, target)}: "


def cut(text: str, model: MarianOnnx, limit: int) -> list[str]:
    """Cuts an over-long sentence at commas, else between words, into pieces the model takes."""
    pieces, current = [], ""
    for part in re.split(r"(?<=,)\s+|\s+", text):
        candidate = (current + " " + part).strip()
        if current and len(model.tokens(candidate)) > limit:
            pieces.append(current)
            current = part
        else:
            current = candidate
    return pieces + ([current] if current else [])


# --- which language a text is in -----------------------------------------------------------

GERMAN = set("der die das und ist nicht ich wir sie es ein eine zu mit auf für von den dem sich auch "
             "noch wie aber wenn dass oder haben wird sind bei nach kann schon mal jetzt".split())
ENGLISH = set("the and is not we you it a an to with on for of that this are be have will can but "
              "if or what so just do there they".split())


def detect(text: str, fallback: str | None = None) -> str | None:
    """en, de or ru by the letters and the most common words; fallback when it cannot tell."""
    letters = re.findall(r"[^\W\d_]", text)
    if not letters:
        return fallback
    cyrillic = sum("а" <= c.lower() <= "я" or c.lower() == "ё" for c in letters)
    if cyrillic / len(letters) > 0.5:
        return "ru"
    words = re.findall(r"[a-zäöüß']+", text.lower())
    german = sum(w in GERMAN for w in words) + 2 * len(re.findall(r"[äöüß]", text.lower()))
    english = sum(w in ENGLISH for w in words)
    if german == english:
        return fallback
    return "de" if german > english else "en"


class LiveTranslator(threading.Thread):
    """Translates the phrases of the live mode in the background, in their order, and writes them
    as paragraphs to path (meeting.live.<target>.txt). The language of each phrase is the
    meeting's if it was chosen, else told from the phrase (short ones take the one before).
    on_result(start, label, text, new_paragraph, tag) gets every translated phrase;
    on_info(message) is told when a model is loaded and when the translation fails."""

    def __init__(self, target: str, meeting_language: str | None, path: str, on_result, on_info):
        super().__init__(daemon=True)
        self.target, self.path = target, path
        self.language = meeting_language if meeting_language in LANGUAGES else None
        self.on_result, self.on_info = on_result, on_info
        self.items = queue.Queue()
        self.translators = {}
        self.failed = False
        self.written = False

    def add(self, start: float, label: str | None, text: str, new_paragraph: bool, tag=None) -> None:
        self.items.put((start, label, text, new_paragraph, tag))

    def finish(self) -> None:
        """Translates what is still waiting, then ends."""
        self.items.put(None)
        self.join()

    def translator_for(self, source: str) -> "Translator | None":
        if source not in self.translators:
            self.on_info(f"{source} -> {self.target}: loading the translation model...")
            self.translators[source] = Translator(source, self.target, report=self.on_info)
        return self.translators[source]

    def run(self) -> None:
        if self.language and self.language != self.target:
            try:
                self.translator_for(self.language)
            except Exception as error:
                self.fail(error)
        last = self.language
        with open(self.path, "w", encoding="utf-8") as out:
            while (item := self.items.get()) is not None:
                start, label, text, new_paragraph, tag = item
                if self.failed:
                    continue
                source = self.language or detect(text, last) or "en"
                last = source
                try:
                    translated = text if source == self.target else self.translator_for(source).text(text)
                except Exception as error:
                    self.fail(error)
                    continue
                shown_label = translate_label(label, self.target) if label else None
                self.on_result(start, shown_label, translated, new_paragraph, tag)
                if new_paragraph:
                    seconds = int(start)
                    clock = f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
                    out.write(("\n\n" if self.written else "") + f"[{clock}] "
                              + (f"{shown_label}: " if shown_label else "") + translated)
                else:
                    out.write(" " + translated)
                out.flush()
                self.written = True
            if self.written:
                out.write("\n")

    def fail(self, error: Exception) -> None:
        self.failed = True
        self.on_info(f"Translation stopped: {error}")


def translate_file(path: str, target: str, out_path: str, source: str | None = None, report=print) -> str:
    """Translates a transcript file line by line into out_path; returns out_path."""
    with open(path, encoding="utf-8") as file:
        lines = file.read().splitlines()
    source = source if source in LANGUAGES else detect(" ".join(lines[:200]), "en")
    if source == target:
        raise ValueError(f"the transcript is already in {target}")
    translator = Translator(source, target, report)
    done, total = [], sum(1 for line in lines if line.strip())
    for number, line in enumerate(lines):
        done.append(translator.line(line))
        if number and number % 20 == 0:
            report(f"  translated {sum(1 for d in done if d.strip())} of {total} paragraphs")
    with open(out_path + ".partial", "w", encoding="utf-8") as out:
        out.write("\n".join(done) + "\n")
    os.replace(out_path + ".partial", out_path)
    return out_path
