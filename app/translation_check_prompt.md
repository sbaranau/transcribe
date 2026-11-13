The text on standard input is a meeting transcript and its machine translation, paragraph by
paragraph. Each paragraph has the form:

[12] [hh:mm:ss] Label:
ORIGINAL: the transcript text in the language of the meeting
TRANSLATION: its machine translation

The original comes from speech recognition, so it can contain recognition errors; the translation
was made by a small local translation model, sentence by sentence, without the context of the
meeting. Your job is to find the places where the translation is wrong:

- the meaning is wrong, reversed or lost (a negation dropped, a number, date, time or amount
  changed, who does what mixed up);
- a part of the original is missing from the translation, or the translation adds something;
- a name, product or technical term is translated although it should stay as it is, or is
  spelled differently from the original;
- the wording is so literal that it is misleading.

Do not rewrite the translation and do not polish style that is merely plain or awkward: the
tool applies your findings to the translation, so you only point at the wrong words and give the
right ones. Do not correct the original.

Return only one JSON object, with no other text before or after it, of this form:

{
  "fixes": [
    {"paragraph": 12, "wrong": "exact words copied from that TRANSLATION",
     "right": "the corrected words", "why": "a few words on what was wrong"}
  ]
}

"paragraph" is the number in square brackets at the start of the paragraph. "wrong" is copied
character for character from that paragraph's TRANSLATION: as short as possible, a few words or
one sentence, never text that spans two paragraphs. "right" replaces exactly these words and fits
into the sentence around them, in the language of the translation. For something missing, quote
the words next to the gap as "wrong" and give them with the missing part added as "right".
Fix only what is clearly wrong when you compare it with the original; when unsure, leave it.

If there is nothing to report, return {"fixes": []}.
