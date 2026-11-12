@echo off
rem Drag one or more recordings (or existing .txt transcripts) onto this file, or double-click
rem it and drag the file into the window. It asks, with numbered answers, for the language,
rem whether to separate speakers (and how many there are), whether to check the text and make a
rem summary with an AI, and which AI. Writes the results into a subfolder next to the recording.
call "%~dp0app\transcribe.cmd" %* --srt --ask
echo.
pause
