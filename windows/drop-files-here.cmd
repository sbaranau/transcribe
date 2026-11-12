@echo off
rem Drag one or more recordings (or existing .txt transcripts) onto this file or onto the
rem "Расшифровать запись" shortcut, or double-click it and drag the file into the window. It asks,
rem with numbered answers, for the language, whether to separate speakers (and how many there
rem are), whether to check the text and make a summary with an AI, and which AI. Writes the
rem results into a subfolder next to the recording.
call "%~dp0transcribe.cmd" %* --srt --ask
echo.
pause
