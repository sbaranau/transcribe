@echo off
rem Drag one or more recordings (or existing .txt transcripts) onto this file, or double-click
rem it and drag the file into the window. It asks, with numbered answers, for the language,
rem whether to separate speakers (and how many there are) and whether to make a summary.
rem Writes <name>.txt and <name>.srt (and <name>.summary.md) into a subfolder next to the file.
call "%~dp0transcribe.cmd" %* --srt --ask
echo.
pause
