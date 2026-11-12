@echo off
rem Transcribes a meeting while it happens: the computer's sound (the other participants in
rem Teams, Zoom, ...) and your microphone. No video is recorded. The text appears in this window
rem and in Documents\Transcripts\<date time>\meeting.live.txt. Press Enter to stop; then it offers
rem the full processing (speakers, check, summary).
call "%~dp0app\transcribe.cmd" --live --ask
echo.
pause
