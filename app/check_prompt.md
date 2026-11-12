The text on standard input is an automatic speech-to-text transcript of a meeting. Each
paragraph has the form "[hh:mm:ss] <label>: text". The labels, such as "Говорящий 2" or
"Speaker 2", come from automatic voice separation. It is mostly right about who is who, but it
makes mistakes at the borders between speakers:

- a sentence is cut in two, and the parts get different labels;
- a short question or remark of one person ends up inside another person's paragraph;
- a short answer gets the label of the person who asked.

Your job is to find these mistakes and the speakers' names. Do not rewrite, shorten, translate or
correct the text itself: the tool applies your findings to the transcript, so you only point at
text and say who said it.

Return only one JSON object, with no other text before or after it, of this form:

{
  "names": [
    {"label": "Говорящий 2", "name": "Анна", "sure": true, "evidence": "00:01:05"}
  ],
  "fixes": [
    {"at": "01:45:00", "text": "exact words copied from that paragraph", "speaker": "Говорящий 2"}
  ]
}

"names": for each label whose person can be named from the transcript. The evidence is direct
when the person introduces themselves ("меня зовут Анна", "это Олег"), or is addressed by name
and answers right after, or is called by name when they are clearly the one speaking. Then set
"sure" to true. If the name is only likely, set "sure" to false. Give the name as it is used in
the meeting. Leave out labels you cannot name. "evidence" is the timestamp of the clearest place.

"fixes": every stretch of text that has the wrong label. "at" is the timestamp of the paragraph
that contains the text, exactly as written there. "text" is copied character for character
from that paragraph: a whole sentence, a part of one, or the whole paragraph; never text that
spans two paragraphs. "speaker" is the label of the person who really said it, one of the labels
used in the transcript. When a sentence is cut between two paragraphs, give a fix for each part
that has the wrong label, so that both parts end up with the same label; the tool then joins
them. Fix only what the context makes clear, such as a question followed by its answer, a name
being addressed, or a sentence that only makes sense as one; when unsure, leave it.

Look in particular for these patterns:

- One paragraph contains a question and, right after it, its answer, such as "...и тут мы
  застряли. Подожди, а сколько это стоит? Около двухсот евро." A person does not ask and then
  answer their own question: the question ("Подожди, а сколько это стоит?") belongs to someone
  else, usually the person leading the conversation, and gets its own fix.
- A paragraph ends in the middle of a sentence ("Павел, а что") and the next one, with another
  label, finishes it ("у тебя по срокам?"): both parts belong to the same person.
- A paragraph starts by finishing the previous person's sentence ("...Если у нас" followed by
  "будет сервер к пятнице, мы успеем"): that part belongs to the previous person.

If there is nothing to report, return {"names": [], "fixes": []}.
