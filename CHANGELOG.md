# Changelog

## v1.35 — 2026-11-21

- macOS: the app bar, the cards and the captions lost their own colours and showed in the plain
  background colour. The macOS build runs Tk 9, where the theme's palette update repaints every
  widget when the window is shown; it is now applied once at start only.

## v1.34 — 2026-11-20

- Icons: the app's icon in the app bar, and small icons from the system's icon font before the
  section headings (meeting setup, transcription of a recording, results, transcript,
  translation, recent results, AI setup) on Windows.
- Copyright and author: "© 2026 sbaranau · MIT License" with the version at the bottom of the home
  screen and in About, and in the Windows installer's and the macOS app's file information.

## v1.33 — 2026-11-20

- A modern look: the window uses the Sun Valley theme (sv-ttk, the Windows 11 Fluent style, also
  on macOS) with rounded buttons and fields, and a new "calm ink-blue" palette instead of the
  grey: slightly blue-tinted neutrals, white cards, a deep indigo app bar with the title, one blue
  accent for the main actions instead of red, green and blue, and calm status colours (every text
  colour at least 4.5:1 contrast). Updates, help and about moved into one "⋯" menu; the work's
  state shows below the bar; the home cards' icons sit on a tinted tile and the transcript in a
  framed field.
- Dark mode: the window follows the system's light or dark setting (Windows and macOS), including a
  dark title bar on Windows. TRANSCRIBE_THEME=light or dark overrides it.

## v1.32 — 2026-11-20

- Windows: the installer could not close a running Live Transcription, because its launcher has
  no window, and Windows then closes nothing at all. The installer now closes it by force where
  needed; the window itself ends cleanly when Windows asks (a running processing is stopped, a
  recording is stopped and saved), also when logging off.

## v1.31 — 2026-11-20

- The AI setup's choice page shows the state of each AI: "Connected" (with the account) for one
  that is ready, "Sign in" for one that is installed without a sign-in, so a connected AI no
  longer looks as if it had to be installed. The unclear "another account" link is now "Back to
  the choice of AI".

## v1.30 — 2026-11-20

- With one AI ready, "Connect another AI…" next to the summary option opens the wizard straight
  on the other one (Claude or ChatGPT, whichever is not ready yet).
- macOS: an update could not be installed while the old version was open. Accepting the update
  offer now downloads the new DMG directly and quits the app (after a running processing, it
  asks to close the app once that is done). Cmd+Q goes through the same checks as closing the
  window, and the DMG's guide says to quit the old version before replacing it.

## v1.29 — 2026-11-20

- Without any AI, the yellow panel has a "Connect an AI…" button on Windows and macOS. It asks
  which account the person has (Claude or ChatGPT), says in plain words what will happen, and one
  button installs Claude Code or the Codex CLI and signs in (`claude auth login`, `codex login`)
  in a visible PowerShell or Terminal window that names each step. The window checks the computer
  every few seconds and says when the AI is ready; an installed AI without a sign-in gets a
  "Sign in" button. The commands, each with a Copy button, are folded away for specialists.
- macOS: Codex and Claude Code in ~/.local/bin are found even when the app is opened from Finder.
- Check with an empty path looks for the AIs again in the background instead of freezing the
  window.

## v1.28 — 2026-11-18

- Processing shows its steps (transcription, speakers, translation, AI check, summary) with
  their state, a percentage and the time left, instead of the raw log; the log is under
  Details, opened by itself when something failed.
- When the processing ends, the results come first: a green panel with the main text as the
  primary button, the translation and summary beside it, the folder, and "Change the settings
  and run again".
- When the window is not in front at that moment, its taskbar button flashes and Windows shows
  a notification (a click opens the text); macOS and Linux show a system notification.
- The meeting setup shows live levels of the microphone and the computer sound before the
  start, and says when the microphone hears nothing.
- The processing options chosen last time (speakers, translation, AI check, summary) are
  offered again.

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
