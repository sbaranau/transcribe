@echo off
rem Drag one or more audio/video files (or existing .txt transcripts) onto this file:
rem writes the full transcript and a summary (.summary.md) made by Claude Code.
rem The summary sends the transcript to Claude under your own account: only for meetings whose
rem content your organization's AI usage rules and Anthropic's terms allow (no unneeded
rem personal or health data, no credentials, no confidential client material).
echo The summary sends the transcript to Claude under your account; your Claude usage rules apply.
choice /c YN /m "May the content of this meeting go to Claude"
if errorlevel 2 (
    echo Cancelled. Use drop-text.cmd for a local transcript only.
    pause
    exit /b 1
)
call "%~dp0transcribe.cmd" %* --srt --summary
echo.
pause
