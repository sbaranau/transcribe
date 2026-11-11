@echo off
rem Drag one or more audio/video files onto this file: writes the full transcript (.txt and .srt).
rem Everything runs locally; nothing is sent anywhere.
call "%~dp0transcribe.cmd" %* --srt
echo.
pause
