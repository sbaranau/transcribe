@echo off
rem Opens the window to transcribe recordings made elsewhere (Teams, Zoom, phone, ...): the files
rem dropped onto this file or onto the "Transcribe a recording" shortcut, or sent with Explorer's
rem Send to; without any, the window asks for them. The results go into a folder named after each
rem recording, next to it. This console only shows technical messages; the window is what people
rem use. drop-files-here.cmd still asks the same questions in the console.
call "%~dp0transcribe.cmd" --files %*
