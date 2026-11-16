$ErrorActionPreference = "Stop"

$WindowsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $WindowsDir
$Version = (Get-Content (Join-Path $Root "VERSION") -Raw).Trim()
$Build = Join-Path $Root "build\windows-release"
$Payload = Join-Path $Build "payload"
$Dist = Join-Path $Root "dist"

if ($Build -notlike "$Root\build\*") { throw "Unsafe build path: $Build" }
if (Test-Path $Build) { Remove-Item -Recurse -Force $Build }
New-Item -ItemType Directory -Force $Payload, $Dist | Out-Null

$AppPayload = Join-Path $Payload "app"
New-Item -ItemType Directory -Force $AppPayload | Out-Null
robocopy (Join-Path $Root "app") $AppPayload /E /XD __pycache__ models python venv /XF *.local.ini | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Could not copy application files (robocopy $LASTEXITCODE)" }

Copy-Item (Join-Path $Root "VERSION"), (Join-Path $Root "LICENSE") -Destination $Payload
Copy-Item (Join-Path $WindowsDir "release\launch-live.vbs") -Destination $Payload
Copy-Item (Join-Path $WindowsDir "release\transcribe-recording.cmd") -Destination $Payload

uv python install 3.12 --install-dir (Join-Path $Build "python-install") --no-bin
$Python = Get-ChildItem (Join-Path $Build "python-install") -Filter python.exe -Recurse |
    Where-Object { $_.FullName -notlike "*\Scripts\*" } | Select-Object -First 1
if (-not $Python) { throw "Bundled Python 3.12 was not created" }
$Runtime = Join-Path $Payload "runtime"
Move-Item $Python.Directory.FullName $Runtime
$Python = Join-Path $Runtime "python.exe"

# The NVIDIA CUDA wheels (about 1.3 GB) are not bundled: app\cuda_runtime.py downloads them on
# first start, only on computers with an NVIDIA driver. Its pinned files must match these pins.
$Requirements = Get-Content (Join-Path $Root "app\requirements.txt")
$CudaRuntime = Get-Content (Join-Path $Root "app\cuda_runtime.py") -Raw
foreach ($line in $Requirements | Where-Object { $_ -match '^nvidia-' }) {
    $pin = ($line -split ';')[0].Trim() -replace '==', '-' -replace '-cu12-', '_cu12-'
    $wheel = ($pin -replace '^nvidia-', 'nvidia_') -replace '-(?=[a-z])', '_'
    if (-not $CudaRuntime.Contains("$wheel-py3-none-win_amd64.whl")) {
        throw "app\cuda_runtime.py does not download $line"
    }
}
$BundledRequirements = Join-Path $Build "requirements-bundled.txt"
$Requirements | Where-Object { $_ -notmatch '^nvidia-' } | Set-Content -Encoding utf8 $BundledRequirements

$Packages = Join-Path $Payload "packages"
uv pip install --target $Packages --only-binary :all: -r $BundledRequirements
if (Test-Path (Join-Path $Packages "nvidia")) { throw "NVIDIA CUDA wheels were bundled" }
$OldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $Packages
& $Python -c "import tkinter, faster_whisper, sherpa_onnx, soundcard, onnxruntime, tokenizers"
$env:PYTHONPATH = $OldPythonPath
if ($LASTEXITCODE -ne 0) { throw "Packaged Python import check failed" }

$Iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
if (-not $Iscc) {
    $candidate = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
    if (Test-Path $candidate) { $Iscc = $candidate }
}
if (-not $Iscc) { throw "Inno Setup 6 (ISCC.exe) is required" }

& $Iscc "/DMyAppVersion=$Version" "/DPayloadDir=$Payload" "/DOutputDir=$Dist" `
    (Join-Path $WindowsDir "installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

$Installer = Join-Path $Dist "Live-Transcription-Windows-x64-v$Version-Setup.exe"
if (-not (Test-Path $Installer)) { throw "Installer was not created: $Installer" }
Write-Output $Installer
