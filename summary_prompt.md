The text on standard input is an automatic speech-to-text transcript of a recorded meeting or
conversation of any kind: a work meeting, call, interview, workshop, webinar or lecture. Each
paragraph starts with its timestamp [hh:mm:ss]. The recognition makes mistakes (wrong words,
misspelled names, misheard numbers).

Paragraphs may also carry a speaker label after the timestamp, such as "Говорящий 2:" or
"Speaker 2:", from automatic voice separation. Then use the labels to say who proposed,
objected, decided or took a task. Where the transcript makes a speaker's name clear (they
introduce themselves, or are addressed by name right before they answer), write the name with
the label, e.g. "Ира (Говорящий 2)", and add "(?)" if it is not certain. The voice separation
can be wrong, for example when people talk at once or voices are similar; if a label looks
wrong in context, say so. Without labels, attribute only what the text itself makes clear.

Write a summary for a reader who did not attend. It must be complete and dense at the same
time:

- **Miss no idea.** Every distinct idea, proposal, argument, conclusion, decision, task and
  open question gets its own bullet, even if it was mentioned only once in passing. Do not merge
  two different ideas into one bullet, and do not drop a point because it seems minor.
- **Miss no date.** Every date and time reference goes into the dates section: calendar dates,
  days of the week, times of day, months, quarters, years, deadlines, durations and relative
  references ("tomorrow", "next week", "in two weeks", "by the end of the quarter"). Keep
  relative references as they were said; the recording date is unknown, so do not convert them.
  Rates such as "per month" or "a day" are not dates; they stay with their numbers in the ideas.
- **No filler.** No introductions ("the meeting discussed..."), no restating, no general
  remarks, no praise or assessment of the meeting. One bullet is one or two short sentences with
  the concrete content: what, who, numbers, reasons. Small talk, greetings and technical problems
  with the call are left out. The length follows the amount of content, not the length of the
  recording.
- **Only what was said.** Do not invent names, owners, dates or numbers, and do not add your own
  advice. Where the transcript is unclear, or a name, number or date looks misrecognized, mark it
  with "(?)" and keep the timestamp, so the reader can check it.
- Every bullet ends with the timestamp of the paragraph where it was said, as [hh:mm:ss].

Work in two passes. First read the whole transcript from start to end and note every idea, date,
task and question in order. Then write the summary. Before you output it, check the transcript
once more for dates, numbers and ideas you have not covered, and add them.

Write the whole summary in Markdown, in the language the meeting was held in: the text, the
section headings and the table header. If several languages were spoken, use the one spoken
most. Use the sections below in this order, with their headings translated into the meeting's
language (the Russian headings are given in brackets). Leave out a section that would be empty,
except the dates section: if no dates or deadlines were mentioned, say so there in one line.

# <short title saying what the meeting was about>

## In short (Коротко)
3 to 5 sentences: what the meeting was about, the main outcome, what happens next.

## Main ideas (Главные идеи)
All ideas, proposals, arguments, conclusions and facts with numbers, grouped under bold topic
names in the order they came up. Note disagreement where it was voiced, and who leaned which way
when it is clear.

## Decisions (Решения)
What was decided or agreed, one bullet each.

## Tasks (Задачи)
A table with the columns what | who | due | timestamp (Что | Кто | Срок | Таймкод), one row per
task or promise to do something. "?" where the transcript does not say.

## Dates and deadlines (Даты и сроки)
A table with the columns date or period, as said | what it refers to | timestamp
(Дата или срок | К чему относится | Таймкод), in the order mentioned. List every date reference
here, even when it already appears in another section.

## Open questions (Открытые вопросы)
Questions left unanswered, postponed topics, risks and concerns raised.

## Topics by time (Темы по времени)
One line per topic: [hh:mm:ss–hh:mm:ss] topic, so the reader can find a passage in the recording.

Output only the Markdown summary, with no preamble and no closing remarks. Do not use any tools.
