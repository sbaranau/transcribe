The text on standard input is an automatic speech-to-text transcript of a meeting. Each
paragraph starts with its timestamp [hh:mm:ss]. Speakers are not labelled, and the
recognition makes mistakes (wrong words, misspelled names and terms).

Write a summary of this meeting in Markdown, entirely in the language the meeting was held
in: the text, the section headings and the table header. If several languages were spoken,
use the one spoken most.
The reader did not attend and must not lose anything important, so prefer completeness
over brevity in the sections on decisions, agreements and open questions. Use only what is
in the transcript: do not invent names, owners, dates or numbers. Where the transcript is
unclear or a word looks misrecognized, say so and give the timestamp, so the reader can
check it.

Use exactly the sections below, in this order, with their headings translated into the
meeting's language. Under a section with nothing in it, write "none" in that language.
For a Russian meeting the headings are given in brackets; for other languages translate
them the same way.

# <short meeting title>

## In short (Коротко)
5 to 10 sentences: purpose of the meeting, main outcome, what happens next.

## Decisions (Решения)
Every decision taken, one bullet each, with timestamp.

## Agreements and tasks (Договорённости и задачи)
A table with the columns what | who | due date | timestamp
(Что | Кто | Срок | Таймкод). "?" where the transcript does not say.

## Open questions and risks (Открытые вопросы и риски)
Everything left unresolved, postponed or raised as a concern, with timestamp.

## Key facts (Ключевые факты)
Numbers, dates, deadlines, names of systems, products, documents or people mentioned
as relevant, with timestamp.

## Course of the meeting (Ход встречи)
The topics in order: for each, its time range [hh:mm:ss–hh:mm:ss] and 2 to 5 sentences
on what was said, including the main arguments and who leaned which way when it is clear.

Output only the Markdown summary, with no preamble and no closing remarks. Do not use any
tools.
