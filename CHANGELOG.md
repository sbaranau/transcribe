# Changelog

## v1.27 — 2026-11-16

- The Windows installer carries a fixed product name and version, and the release workflow is
  prepared for free code signing by SignPath Foundation and for publishing to winget; both are
  switched on once they are set up (docs/SIGNING.md). Until then the installer stays unsigned.
- The project page has a code signing policy and a privacy statement that says exactly what the
  program downloads and what it sends, and when.

## v1.26 — 2026-11-16

- The processing log can be scrolled back and read while it runs: new lines follow only while
  the end is in view, otherwise a To the end button appears.
- During processing the locked options fold away, so the log gets most of the window; they
  return when it ends or is stopped.

## v1.25 — 2026-11-16

- The window opens on a home screen with two equal choices, "Meeting now" and "Existing
  recording", and the last five results (click to open their folder). The meeting settings are
  their own screen with a Back button, so transcribing a file is no longer hidden below them.
- More AIs are found for the check and the summary: Gemini CLI, GitHub Copilot CLI and Qwen
  Code, each with the user's own account login (no API keys), and local model servers on the
  default ports of Ollama, LM Studio, Jan, GPT4All, Msty, KoboldCpp, text-generation-webui,
  llama.cpp, LocalAI, vLLM, Docker Model Runner and LiteLLM.

## v1.24 — 2026-11-16

- The AI options (text check, summary, translation check) are not offered when no AI is ready
  on the computer. A panel says what to install and how to sign in (Claude Code, ChatGPT through
  the Codex CLI, or a local model in Ollama or LM Studio), why an installed AI is not usable,
  and has a Search again button. While AIs are looked for, these options wait greyed out.

## v1.23 — 2026-11-16

- Recordings made elsewhere are transcribed in the window instead of a console with numbered
  questions: a **Transcribe a recording…** button on the start screen, and the Transcribe a
  recording shortcut, Explorer Send to and the Linux menu open the window with the files. The
  same check boxes as after a live recording, progress, and buttons to open each result.
- The language of such a recording is detected by default instead of taking the last live
  meeting's language.
- The console questions remain in `drop-files-here.cmd` / `.sh`.

## v1.22 — 2026-11-15

- Added a single-file per-user Windows installer built and published by GitHub Actions.
- Bundled an isolated Windows Python environment while keeping speech models and preferences in
  LocalAppData so updates do not download them again.
- Added Start menu shortcuts, optional desktop and Explorer Send to entries, and standard Windows
  uninstall support.
- Kept the repository setup as a separate source/developer installation.
- Limited the repeated security-approval update warning to macOS; Windows receives its own
  SmartScreen guidance in the documentation.
- Rebuilt Windows installer (same version): fixed the installed app exiting silently at start,
  because the install folder name contains a space. macOS is unchanged.
- Windows installer no longer bundles the NVIDIA CUDA libraries (about 1.3 GB): on computers
  with an NVIDIA driver they are downloaded once at first start, so the GPU is actually used by
  the installed app; other computers run on the CPU as before.

## v1.21 — 2026-11-15

- Added a clear update-dialog warning that each non-notarized macOS build must be approved again
  in Privacy & Security after installation.
- Includes the persistent result actions and high-contrast processing controls from the latest UI.

## v1.9 — 2026-11-15

- Kept Open, New recording and Close actions visible when the window is made smaller.
- Reserved a persistent results footer and set a practical minimum window size.

## v1.8 — 2026-11-15

- Renamed the Russian processing action to the clearer "Выполнить расшифровку".
- Made the processing action reliably prominent and high-contrast on macOS Aqua.

## v1.7 — 2026-11-15

- Added a bilingual first-launch guide directly inside the macOS DMG.
- Explained the independent open-source distribution and current lack of Apple notarization.
- Documented the reliable Privacy & Security approval flow used by current macOS releases.

## v1.6 — 2026-11-15

- Made the primary Start recording action reliably bright red on macOS Aqua.
- Updated the project page and screenshots for the complete current macOS workflow.
- Added a prominent direct installer download link for regular macOS users.

## v1.5 — 2026-11-15

- Made Start recording larger and brighter as the primary action.
- Hid update, help and about controls while recording to keep the active screen focused.
- Added a distinct dark microphone icon with a bright recording dot while recording is active;
  the normal application icon returns after stopping.

## v1.4 — 2026-11-15

- Added a prominent New recording button after stopping and after result processing.
- A new recording returns to the setup screen without restarting the application process.
- New session folders include seconds and a collision-safe suffix, so consecutive recordings
  can never overwrite one another.

## v1.3 — 2026-11-15

- Added a single-file Apple Silicon DMG for people who do not need the source tree.
- Added a first-run application window that downloads speech models into Application Support.
- Kept models and settings outside the app so updates do not download them again.
- Added a quiet GitHub Releases update check with a prompt when a newer version is available.
- Added visible Check for updates, Help and About buttons to the live window.
- Added an ARM64 GitHub Actions release build that attaches the DMG to version tags.
- Kept the repository-based installation as a separate developer/source distribution.

## v1.2 — 2026-11-14

- Added a native macOS installation and launch workflow.
- Redesigned the live interface around clear preparation, download, recording, finalization and
  result states.
- Added editable output-folder selection and collapsible additional settings.
- Added first-use translation-model download with progress and locked controls.
- Added explicit finalization stages so stopping a recording no longer looks frozen.
- Separated live drafts from confirmed transcript text and made the translation column hideable.
- Simplified result creation and made completed files easier to find.
- Added macOS audio compatibility fixes and platform-specific dependency handling.

## v1.1 — 2026-11-13

- Added screenshots during live meetings and placed them into Markdown transcripts.
- Added self-contained HTML export for transcripts with screenshots.

## v1.0 — 2026-11-13

- First public release.
