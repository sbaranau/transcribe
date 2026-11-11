@echo off
rem Writes transcribe-package.zip next to this folder: every top-level file (scripts and guides),
rem without the python\, venv\ and models\ folders and without personal *.local.txt files.
rem Recipients unpack it and run setup.cmd.
setlocal
set "TOOL_DIR=%~dp0"
"%TOOL_DIR%venv\Scripts\python.exe" -c "import os, sys, zipfile; d = os.path.abspath(sys.argv[1]); out = os.path.join(os.path.dirname(d), 'transcribe-package.zip'); names = sorted(n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n)) and not n.lower().endswith('.local.txt')); z = zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED); [z.write(os.path.join(d, n), 'transcribe/' + n) for n in names]; z.close(); print('Package written:', out); print(*names, sep='\n')" "%TOOL_DIR%."
exit /b %ERRORLEVEL%
