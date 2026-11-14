# transcribe

Private, local meeting transcription for Windows, macOS and Linux. Recordings and live calls
become a readable transcript with speakers and timestamps, optionally translated, checked and
summarized.

**Current release: v1.2** — macOS support and a redesigned live interface with clearer setup,
download progress, recording states and result creation. See the [changelog](CHANGELOG.md).

![The live window during a call: the transcript on the left, its German translation on the right](docs/screenshots/2-live.png)

## What it does

- **Transcribes recordings** (video or audio: mp4, mkv, mp3, wav, m4a, ...) with Whisper
  `large-v3-turbo`, on an NVIDIA GPU or the CPU. A 3-hour meeting takes about 10 minutes on the GPU.
- **Transcribes calls while they happen** (Teams, Zoom, ...): your microphone and the computer's
  sound, without recording video. Your words are labelled "You", the other side is told apart by
  voice. A draft of each phrase shows after 2–3 seconds; the final text follows in 20–30 second
  pieces, nearly as accurate as transcribing the recording afterwards.
- **Tells speakers apart** by voice ("Speaker 1", "Speaker 2", ...); on public test meetings (AMI,
  4 people) 98% of the words went to the right person when the number of speakers was given.
- **Takes screenshots** with a button during a call (the slide or document being shown) and puts
  each one into the transcript at its moment: `meeting.md`, readable in any Markdown viewer.
- **Translates** between English, German and Russian locally (Opus-MT), live in a second column
  or afterwards.
- **Optional AI steps** with an AI you have installed (Claude Code, ChatGPT through the Codex CLI,
  or a local model in Ollama or LM Studio): put in names and fix speaker borders, correct the
  translation, and write a summary that keeps every decision, task and date.
- **Interface in English, German and Russian.**
- **Guided live interface** that clearly separates setup, model download, recording, finalization
  and result creation, with accessible progress and error states.

**Privacy.** Transcription, speaker separation and translation run locally; no recording or text
leaves the computer. Only the optional AI steps send the text to the AI you choose, under your
own account, and only when you tick them. Use those only for meetings whose content the rules you
work under allow. Tell the participants that a meeting is transcribed.

## Install

### Windows 10/11

Needs `git` (`winget install --id Git.Git`), about 4 GB of disk (plus about 0.45 GB per
translation direction, downloaded when first used) and an internet connection during the setup. An NVIDIA GPU is recommended; without one, everything runs on the CPU, several times
slower.

```
git clone https://github.com/sbaranau/transcribe.git C:\bin\transcribe
C:\bin\transcribe\windows\setup.cmd
```

The setup installs [uv](https://docs.astral.sh/uv/) with winget if needed, then a private Python,
the packages and the models into `app\`; nothing else on the computer is changed. At the end it
makes three shortcuts with icons in the tool folder. Update with `git pull` and run the setup
again.

### macOS

Clone the repository, then double-click `macos/setup.command`:

```bash
git clone https://github.com/sbaranau/transcribe.git
cd transcribe
open macos/setup.command
```

After setup, use `Transcribe recording.command` or `Live transcription.command` in `macos/`.
Recognition runs locally on the CPU. Translation models are downloaded with visible progress when
a language pair is first selected. Live mode records a microphone; system audio requires a virtual
CoreAudio loopback device, which can be selected as a microphone. macOS asks for microphone access
on first use.

### Linux

Run `linux/setup.sh`. Linux supports files and live transcription through PulseAudio/PipeWire, but
is less tested. See the [technical description](docs/TECHNICAL.md#macos-and-linux).

## Use

| Shortcut | What it does |
|---|---|
| **Transcribe a recording** | Drag recordings onto it. It asks the language, whether to separate speakers, translate, check or summarize, and writes the results next to the recording. |
| **Live meeting transcription** | Opens the window above. Choose the language and, if wanted, a translation, then start before the call. After Stop, the same window offers the full processing. |
| **Setup and update** | Runs the setup again. |

The shortcut names follow the interface language. You can switch it at the top right of the
window, or with `--ui-language en|de|ru`.

The live workflow has five explicit states: preparation, translation-model download, recording,
finishing the last phrases, and creating results. The folder can be edited or chosen with the
system dialog; less-used options stay under **Additional settings**. During recording, drafts are
shown separately from confirmed text and the translation column can be hidden temporarily.

<p>
<img src="docs/screenshots/1-before.png" alt="Before the call: meeting language, translation, microphone and computer sound" width="49%">
<img src="docs/screenshots/3-after.png" alt="After the call: transcribe again, speakers, translation, AI check and summary" width="49%">
</p>

The results of a recording go into a folder next to it:

| File | Content |
|---|---|
| `<name>.txt`, `<name>.srt` | the transcript in paragraphs with `[hh:mm:ss]` timestamps (and speakers), and subtitles |
| `<name>.checked.txt` | with names put in and speaker borders fixed by the AI |
| `<name>.de.txt`, `<name>.de.checked.txt` | the translation, and its AI-corrected version |
| `<name>.summary.md` | the summary: main ideas, decisions, tasks, every date mentioned, open questions |
| `meeting.md`, `screenshots/` | with screenshots taken during the call: the transcript as Markdown with each screenshot at its moment; "Export to HTML" in the window makes `meeting.html` with the pictures inside, for any browser |

From a terminal, `windows\transcribe.cmd` takes the same choices as options, for example:

```
windows\transcribe.cmd meeting.mp4 --language en --speakers 4 --translate de --summary --srt
windows\transcribe.cmd --help
```

## Documentation

- [ИНСТРУКЦИЯ.md](ИНСТРУКЦИЯ.md): the full user guide (in Russian).
- [docs/TECHNICAL.md](docs/TECHNICAL.md): how it works, what was measured, all options.
- [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md): the models and packages it uses, and their licenses.

## License

[MIT](LICENSE). The models and packages that the setup downloads come under their own licenses,
listed in [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md).
