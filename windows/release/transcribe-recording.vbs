' Opens the window to transcribe recordings, without a console: the files dropped on the
' "Transcribe a recording" shortcut or sent with Explorer's Send to, or, without any, a file
' dialog in the window.
Option Explicit

Dim shell, files, base, data, python, script, command, index
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")

base = files.GetParentFolderName(WScript.ScriptFullName)
data = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Live Transcription"
python = base & "\runtime\pythonw.exe"
script = base & "\app\bootstrap.py"

shell.Environment("PROCESS")("TRANSCRIBE_DATA_DIR") = data
shell.Environment("PROCESS")("TRANSCRIBE_CONFIG_DIR") = data
shell.Environment("PROCESS")("TRANSCRIBE_VERSION_FILE") = base & "\VERSION"
shell.Environment("PROCESS")("TRANSCRIBE_CHECK_UPDATES") = "1"
shell.Environment("PROCESS")("HF_HOME") = data & "\huggingface"
shell.Environment("PROCESS")("HF_HUB_DISABLE_SYMLINKS_WARNING") = "1"
shell.Environment("PROCESS")("PYTHONIOENCODING") = "utf-8"
shell.Environment("PROCESS")("PYTHONUTF8") = "1"
shell.Environment("PROCESS")("PYTHONPATH") = base & "\packages"

command = Chr(34) & python & Chr(34) & " " & Chr(34) & script & Chr(34) & " --files"
For index = 0 To WScript.Arguments.Count - 1
    command = command & " " & Chr(34) & WScript.Arguments(index) & Chr(34)
Next
shell.Run command, 0, False
