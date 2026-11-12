@echo off
rem Transcribes a meeting while it happens, in its own window: the computer's sound (the other
rem participants in Teams, Zoom, ...) and your microphone. No video is recorded. The text goes to
rem Documents\Transcripts\<date time>\meeting.live.txt; after Stop, the window offers the full
rem processing (speakers, check, summary). This console only shows technical messages.
call "%~dp0transcribe.cmd" --live
