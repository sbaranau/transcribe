# transcribe

Turns meeting recordings (video or audio) into a full, readable transcript and, on request,
a structured summary.

- **Transcript**: runs locally with Whisper (`faster-whisper`, model `large-v3-turbo`) on the
  NVIDIA GPU, or on the CPU if no GPU is available. Nothing leaves the machine. A 3-hour
  recording takes about 10 minutes on the GPU.
- **Summary**: made by Claude Code (`claude -p`) under your own account. It sends the transcript
  to Claude, so it is only for meetings whose content the rules you use Claude under allow (your
  organization's AI usage rules for a work account, and Anthropic's terms): typically no
  personal data beyond what is needed and never health or other special categories, no
  credentials, no confidential client material. Anything else gets the local transcript only.

Nothing is tied to one person's account. The transcript needs no account, and the model is
downloaded from Hugging Face without login. The summary uses the Claude Code login of whoever
runs the tool, and calls it with `--tools "" --strict-mcp-config --setting-sources project
--no-session-persistence` from this folder, so that person's own settings, hooks and MCP
servers stay out and no session keeps the transcript.

To share the tool, give out the package from `make-package.cmd` (scripts only, ~30 KB); each
person runs `setup.cmd`. Do not copy `python\` or `venv\`: the environment is bound to its
folder path, so after moving the folder run `setup.cmd` again. A Russian guide is in
`ИНСТРУКЦИЯ.md`.

## Usage

Drag files in Explorer onto:

| Script | Result |
|---|---|
| `drop-text.cmd` | `<name>.txt` and `<name>.srt`, local only |
| `drop-text-summary.cmd` | the same plus `<name>.summary.md`; asks first whether the content may go to Claude |

Optionally the same two scripts are in the Explorer **Send To** menu (right-click a recording,
Send To, "Расшифровать (текст)" / "Расшифровать (текст и выжимка)"). `setup.cmd` asks whether
to add them; `send-to-menu.cmd add|remove|status` changes it later. Only these two shortcuts in
the user's own SendTo folder are touched.

Or from a terminal:

```
C:\bin\transcribe\transcribe.cmd "meeting.mp4" --language ru
C:\bin\transcribe\transcribe.cmd "meeting.mp4" --language ru --summary --srt
C:\bin\transcribe\transcribe.cmd "meeting.txt" --summary        (summarize an existing transcript)
C:\bin\transcribe\transcribe.cmd --help
```

Options: `--language ru|de|en|...` (default: detected from the first 30 seconds; set it for
mixed-language meetings), `--summary`, `--srt`, `--terms FILE`, `--no-terms`, `--no-filter`, `--out-dir DIR`,
`--cpu`, `--model`, `--force`.

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

Names and jargon Whisper should spell right go one per line into `terms.txt` (shared with the
team through the package) or `terms.local.txt` (personal, e.g. colleague names; never
packaged). Neither is in git, so company terms never reach the repository; create them next to
`transcribe.py`. Both are optional; `--terms FILE` adds a
file for one meeting. They are passed to Whisper as `hotwords` for every 30-second window,
most specific first: `--terms` files, then `terms.local.txt`, then `terms.txt`. Whisper reads
at most 223 tokens (roughly 60-100 terms) and drops the rest; the tool prints the token count
and warns when the list is too long. Add only terms that actually come out wrong: hints for
words that are never said can occasionally leak into the text.

## Output

Each recording gets a subfolder named after it, next to the recording
(`D:\rec\meeting.mp4` -> `D:\rec\meeting\meeting.txt`, ...), unless `--out-dir` says otherwise.
For a `.txt` input, the summary is written next to that `.txt`.

- `<name>.txt`: the full transcript in paragraphs. Each paragraph starts with its
  `[hh:mm:ss]` timestamp, so a passage can be found in the recording. A new paragraph starts
  at the first sentence end after about 30 seconds (at the latest after 90 seconds), or after
  a pause of 2 seconds or more.
- `<name>.srt`: subtitles with exact segment timings. Players pick them up automatically only
  from the recording's folder, so load them by hand (VLC: Subtitle > Add Subtitle File), or move
  the `.srt` next to the recording.
- `<name>.summary.md`: In short, Decisions, Agreements and tasks, Open questions and risks,
  Key facts, Course of the meeting, all with timestamps; written entirely in the meeting's
  language, headings included. Check it against the transcript before
  passing it on. The prompt is in `summary_prompt.md`.

Speakers are not labelled, and recognition makes mistakes with names and technical terms.

## Folder layout

| Path | Content |
|---|---|
| `transcribe.py` | the tool |
| `summary_prompt.md` | the instructions Claude gets for the summary |
| `terms.txt` | shared terms for Whisper (optional; packaged, not in git) |
| `terms.local.txt` | personal terms (optional, not packaged) |
| `requirements.txt` | pinned packages (`av` must stay below 15 for faster-whisper 1.2.1) |
| `python\` | private Python 3.12 (installed by uv) |
| `venv\` | virtual environment with the packages and the NVIDIA CUDA libraries |
| `models\large-v3-turbo\` | the Whisper model, so it works offline |
| `setup.cmd` | rebuilds `python\`, `venv\` and `models\`, e.g. on another machine; needs `uv`; asks about the Send To menu |
| `send-to-menu.cmd`, `send_to_menu.py` | add or remove the Send To menu entries |
| `make-package.cmd` | writes `transcribe-package.zip` next to this folder, with the scripts and guides only |
| `ИНСТРУКЦИЯ.md` | user guide in Russian |
