# transcribe

Turns recordings of any meeting (video or audio: meetings, calls, interviews, webinars,
lectures) into a full, readable transcript and, on request, a dense summary that keeps every
idea, task and date.

- **Transcript**: runs locally with Whisper (`faster-whisper`, model `large-v3-turbo`) on the
  NVIDIA GPU, or on the CPU if no GPU is available. Nothing leaves the machine. A 3-hour
  recording takes about 10 minutes on the GPU.
- **Speakers** (optional): voice separation with [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
  (pyannote segmentation 3.0 + NVIDIA NeMo TitaNet-small embeddings) on the CPU, in parallel
  with Whisper, labels paragraphs "Speaker 1", "Speaker 2", ... (in the meeting's language).
- **Summary**: made by an AI the user has installed, chosen at the start: Claude Code
  (`claude -p`), ChatGPT through the OpenAI Codex CLI (`codex exec`), or a local model server
  with an OpenAI-style API (Ollama, LM Studio, Jan, llama.cpp, ...). Claude and ChatGPT get the
  transcript under the user's account, so the summary is only for meetings whose content the
  rules the user works under allow (the organization's AI usage rules for a work account, and
  the provider's terms): typically no personal data beyond what is needed and never health or
  other special categories, no credentials, no confidential client material. A local model
  keeps the text on the computer. Anything else gets the local transcript only.

Nothing is tied to one person's account. The transcript needs no account, and the models are
downloaded without login. The summary uses the login of whoever runs the tool, with that
person's own setup kept out (`app\ai_engines.py`): Claude Code with `--tools "" --strict-mcp-config
--setting-sources project --no-session-persistence`, Codex with `--ignore-user-config
--ignore-rules --ephemeral --sandbox read-only` in an empty folder; no session keeps the
transcript.

## Install and update

Needs Windows and `git` (`winget install --id Git.Git`). [`uv`](https://docs.astral.sh/uv/) is
installed by `setup.cmd` with `winget install --id astral-sh.uv` when it is missing (winget may
ask you to accept its agreements; the script accepts nothing for you):

```
git clone https://github.com/sbaranau/transcribe.git C:\bin\transcribe
C:\bin\transcribe\setup.cmd
```

`setup.cmd` puts a private Python 3.12, the packages (with the NVIDIA CUDA libraries) and the
models (`app\download_models.py`: Whisper and the voice separation models) into `app\`, about
3 GB. Update with `git -C C:\bin\transcribe pull`, and run `setup.cmd` again when
`app\requirements.txt` or the models changed; models already there are not downloaded again.
The environment is bound to its folder path: after moving the folder, run `setup.cmd` again.
Installs from before 2026-11-12 had `python\`, `venv\` and `models\` at the top level; after
pulling, run `setup.cmd` once: it moves the models into `app\models` and rebuilds the rest there.
A Russian guide is in `ИНСТРУКЦИЯ.md`.

## Usage

Drag recordings in Explorer onto `drop-files-here.cmd` (or double-click it and drag a file into
the window). It writes `<name>.txt` and `<name>.srt` and asks, in Russian, with numbered answers
(Enter = "don't know" / "no"): the language (Russian, English, German, French, several
languages, or detect), whether to separate speakers and how many there are (or estimate),
whether an AI should check the text (only with speakers), whether to make a summary, and, if
either is wanted, which of the AI tools found on the computer to use.

If no AI is found, it offers to skip the check and summary (the transcript is made anyway) or to enter
the path to `claude.exe` / `codex.cmd` (or their folder) or the address of a local model server.
A working path is stored in `app\ai.local.ini` (not in git) and found again next time; delete the
file to search afresh.

**Live**: `live-transcribe.cmd` transcribes a meeting while it happens, without a video
recording; see "Live mode" below.

Optionally the drop script is in the Explorer **Send To** menu (right-click a recording, Send
To, "Расшифровать"). `setup.cmd` asks whether to add it; `send-to-menu.cmd add|remove|status`
changes it later. Only the tool's own shortcut in the user's SendTo folder is touched.

From a terminal, for options the questions do not cover or for many files without questions
(`app\transcribe.cmd` is kept out of the top level, where people would take it for the main
entry point):

```
C:\bin\transcribe\app\transcribe.cmd "meeting.mp4" --language ru
C:\bin\transcribe\app\transcribe.cmd "meeting.mp4" --language ru --speakers 3 --check --summary --srt
C:\bin\transcribe\app\transcribe.cmd "meeting.mp4" --ask             (the questions, as when dragging)
C:\bin\transcribe\app\transcribe.cmd "meeting.txt" --check --summary (check and summarize an existing transcript)
C:\bin\transcribe\app\transcribe.cmd --help
```

Options: `--language ru|de|en|...|multi` (default: detected from the first 30 seconds; `multi`
detects the language for every 30-second window), `--speakers [N]` (label speakers; N if the
number is known), `--ask`, `--check`, `--summary`, `--ai claude|codex|local` (default: the
first one found), `--srt`, `--terms FILE`, `--no-terms`, `--no-filter`, `--out-dir DIR`, `--cpu`,
`--model`, `--force`.

## Live mode

`live-transcribe.cmd` (`app\transcribe.cmd --live --ask`, code in `app\live.py`) listens to the
default microphone and, through WASAPI loopback, to every output device (so the other side of a
Teams or Zoom call is heard whichever device the call plays on), with
[soundcard](https://github.com/bastibe/SoundCard) (BSD-3-Clause). Each device is read in its own
thread in 0.25 s blocks; the microphone sets the pace, a loopback block that is not there yet is
silence (loopback delivers zeros on time when nothing plays), a device that fails is dropped. The
mix goes to `meeting.wav` (16 kHz mono) and is cut into pieces of 8-25 s at the quietest moment
near a pause; silent pieces are skipped. A worker thread transcribes the pieces with the same
Whisper settings and filter as files and writes `meeting.live.txt` and the console. Enter stops
it; the rest is transcribed. Then it offers to process `meeting.wav` in full with the usual
questions (speakers, check, summary), or to summarize the live text, and asks whether to keep
the sound. Default folder: `Documents\Transcripts\<yyyy-mm-dd hh-mm>`, or `--out-dir`.

Tested with speech played through the speakers (33 s, eight sentences): every sentence came out
right, 2-8 s after it was said, and the full processing ran. Not yet tested: a real call, a
long meeting, a computer without an NVIDIA GPU. Speakers are separated only in the full
processing afterwards; participants should be told that the meeting is transcribed.

## Summary AI

`app\ai_engines.py` finds the AI tools (Claude Code and Codex on PATH or at a remembered path;
local servers at a remembered address or the default ports 11434 for Ollama and 1234 for LM
Studio) and calls them. Everything goes through stdin, so no transcript text passes a command
line. Local models get the transcript at once if it is up to 20,000 characters; a longer one is
cut into parts at paragraph ends, each part is turned into notes (`app\summary_notes_prompt.md`),
and the summary is made from the notes. For Ollama the native API is used so the context window
can be set (16,384 tokens); `app\ai.local.ini` `[local]` takes `model`, `chunk_chars` and
`context`.
Tested: Claude and ChatGPT (Codex CLI 0.167) on a synthetic meeting; the local path against
fake Ollama- and LM Studio-style servers only.

## Text check

`--check` (with speaker labels only) has the AI put in names and fix text with the wrong
speaker, into `<name>.checked.txt`; the summary is then made from that file. The AI does not
rewrite the transcript: it returns JSON (`app\check_prompt.md`) with names per label (sure or
not) and fixes, each a quote from one paragraph plus the label of the person who really said
it. `app\checker.py` applies them: a quote must be found in that paragraph word for word (any
whitespace), otherwise the fix is dropped; the paragraph is split around it; then neighbouring
pieces with the same speaker are joined when the first does not end a sentence, which repairs
sentences cut between two labels. Labels become names ("Name (?)" when not sure); a name given
to two labels is used for neither. The words, their order and the timestamps never change,
`<name>.txt` stays as it was, and the first line of the checked file lists what was applied.
Cloud AIs get the whole transcript at once (up to 200,000 characters per request), local models
parts of `chunk_chars`.

Tested on a synthetic meeting with the typical mistakes (a question cut between two labels, the
end of a turn given to the next speaker, a question inside someone else's answer, names given
by introduction and by address): Claude and ChatGPT both found all of them and the three names;
bad suggestions (quote not in the text, unknown label, wrong timestamp) are skipped.

## Speakers

`--speakers` runs the voice separation on the CPU in a thread while Whisper transcribes, then
assigns every word to the speaker who talks most during it; a speaker change starts a new
paragraph and subtitle. Speakers are numbered by first appearance.

How the speakers are found (`diarize`, `refine_speakers`):

1. sherpa-onnx splits the speech into voice groups with a low clustering threshold
   (`SPEAKER_THRESHOLD` 0.85), so one person often ends up in many groups: 80 on a 3-hour
   recording with 4 people.
2. Each group gets an average voice embedding from up to 30 s of its longest turns; groups at
   least `SAME_PERSON_SIMILARITY` (0.72) alike are joined, step by step.
3. Persons with less than 2% of the speech are taken as fragments and folded into the most
   alike person, except, when the number of speakers is given, that many of the most talkative
   persons (so someone who joined late or said little stays separate).
4. With a given number, the most alike persons are joined until that number is left.
5. Inside every turn longer than 3 s, the voice is checked every 0.75 s over 1.5 s windows; a
   stretch at least 0.2 more alike another person's average voice goes to that person
   (`check_voice_inside_turns`). This splits off short interjections the segmentation missed.

sherpa-onnx's own fixed-count mode is not used: on the 4-person recording it merged two people
and kept a 0.4% noise group. Measured: on that recording the steps give 4 persons (61, 20, 10,
9% of the speech) whether the number is given or not; on the sherpa-onnx reference recordings
(one with 4 speakers, three with 2) every count is right in both modes. Joining at any value
from 0.70 to 0.75 gave the same 4 persons; different people on the reference recordings are
0.12-0.43 alike. TitaNet-small was chosen over WeSpeaker ResNet34, CAM++ and ERes2Net, which
counted the reference speakers worse; a segmentation window shift of 0.25 instead of 0.1 gave
the same counts at about a third of the time.

Word-level accuracy against reference speaker timing, on three AMI meetings (ES2004a, IS1009a,
TS3003a; 4 people each, 55 minutes): with the number of speakers given, 98.2% of the words go to
the right person, and 88.7% of the words in turns under 2 s (82.1% without step 5). Without the
number, 97.6% and 87.7%; on TS3003a two people were joined. Tried and dropped: window shift
0.1 (no better, twice as slow) and joining thresholds of 0.75-0.85 (worse). Give the number
when it is known, and check the labels where people talk at once.

Existing results are kept: a recording whose `<name>.txt` exists is not transcribed again (so
hand corrections survive; with `--summary` only a missing summary is made from that `.txt`),
and an existing `<name>.summary.md` is not redone. `--force` overwrites. The transcript is
written to `<name>.txt.partial` and renamed when complete, so an interrupted run leaves no
half transcript behind.

## Hallucination filter

Whisper was trained on subtitled video and sometimes invents text in silence or noise. Each
window is decoded without the previous text (`condition_on_previous_text=False`), so one error
does not spread, and the transcript is filtered: short segments with known invented phrases
("Продолжение следует", "Субтитры сделал ...", "Thanks for watching", "Untertitel im Auftrag
...") are dropped, a phrase repeated four or more times in a row inside a segment is collapsed
to one, and a segment of three or more words that repeats the previous one word for word is
dropped. The tool prints what it removed (`Filtered: ...`); `--no-filter` keeps everything.

## Terms

Names and jargon Whisper should spell right go one per line into `terms.txt` in the tool folder,
next to `setup.cmd` (optional). It is not in git, so company product names and colleague names
never reach the repository; to share it, send the file. `--terms FILE` adds a file for one
meeting. The terms are passed to Whisper as `hotwords` for every 30-second window, `--terms`
files first, then `terms.txt`. Whisper reads
at most 223 tokens (roughly 60-100 terms) and drops the rest; the tool prints the token count
and warns when the list is too long. Add only terms that actually come out wrong: hints for
words that are never said can occasionally leak into the text.

## Output

Each recording gets a subfolder named after it, next to the recording
(`D:\rec\meeting.mp4` -> `D:\rec\meeting\meeting.txt`, ...), unless `--out-dir` says otherwise.
For a `.txt` input, the summary is written next to that `.txt`.

- `<name>.txt`: the full transcript in paragraphs. Each paragraph starts with its
  `[hh:mm:ss]` timestamp, so a passage can be found in the recording. A new paragraph starts
  at the first sentence end after about 30 seconds (at the latest after 90 seconds), after
  a pause of 2 seconds or more, or (with `--speakers`) when the speaker changes; then the
  timestamp is followed by the speaker label.
- `<name>.srt`: subtitles timed by word timestamps; a Whisper segment is split where its words
  are a second or more apart, so a subtitle or paragraph never spans a long pause. Players pick them up automatically only
  from the recording's folder, so load them by hand (VLC: Subtitle > Add Subtitle File), or move
  the `.srt` next to the recording.
- `<name>.checked.txt` (with `--check`): the transcript with names and corrected speaker labels.
- `<name>.summary.md` (made from the checked text if there is one): In short, Main ideas (every idea, proposal, argument and number, grouped
  by topic), Decisions, Tasks (what, who, due, timestamp), Dates and deadlines (every date
  reference, relative ones kept as said), Open questions, Topics by time. Every bullet has a
  timestamp; empty sections are left out except the dates. Written entirely in the meeting's
  language, headings included, without introductions or repetition. Check it against the
  transcript before passing it on. The prompt is in `app\summary_prompt.md`; the first line names
  the AI that made it.

Recognition makes mistakes with names and technical terms, and the speaker labels with
overlapping speech, similar voices and people who say very little.

## Folder layout

The top level holds only what people start or read; everything else is in `app\`.

| Path | Content |
|---|---|
| `drop-files-here.cmd` | drag-and-drop entry point with the questions |
| `live-transcribe.cmd` | live transcription during a meeting |
| `setup.cmd` | installs `uv` with winget if missing; builds `app\python\`, `app\venv\` and `app\models\`, e.g. on another machine; asks about the Send To menu; moves an old top-level layout into `app\` |
| `send-to-menu.cmd` | add or remove the Send To menu entry |
| `ИНСТРУКЦИЯ.md`, `README.md` | user guide in Russian, this file |
| `terms.txt` | your terms for Whisper (optional, not in git) |
| `app\transcribe.cmd` | command-line entry point |
| `app\transcribe.py` | the tool |
| `app\live.py` | live mode: capture, mixing, transcription in pieces |
| `app\ai_engines.py` | finding and calling the AI for the check and the summary |
| `app\checker.py`, `app\check_prompt.md` | the text check: applying the AI's findings; the instructions it gets |
| `app\summary_prompt.md` | the instructions the AI gets for the summary |
| `app\summary_notes_prompt.md` | notes per part of a long transcript, for local models |
| `app\download_models.py`, `app\send_to_menu.py` | model download, Send To shortcut |
| `app\requirements.txt` | pinned packages (`av` must stay below 15 for faster-whisper 1.2.1) |
| `app\ai.local.ini` | where the summary AI was found, if a path was entered (not in git) |
| `app\python\` | private Python 3.12 (installed by uv) |
| `app\venv\` | virtual environment with the packages and the NVIDIA CUDA libraries |
| `app\models\large-v3-turbo\` | the Whisper model, so it works offline |
| `app\models\diarization\` | the voice separation models |
