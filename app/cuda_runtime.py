"""NVIDIA CUDA libraries for the packaged Windows application, downloaded on first start.

The Windows installer leaves out cuBLAS, cuDNN and NVRTC (about 1.3 GB) because most of its
users have no NVIDIA graphics card. On a computer with the NVIDIA driver (nvcuda.dll) they are
downloaded once from PyPI into the data folder, so they survive application updates. Only the
DLLs of the pinned wheels are kept; each wheel is checked against its SHA-256 before use.

A source checkout gets the same libraries through pip (requirements.txt), so nothing is
downloaded there. Keep the versions below equal to the nvidia-* pins in requirements.txt
(windows/build-release.ps1 checks this).

Run as a script, it downloads what is missing and exits 0 also when the computer has no NVIDIA
driver; it exits 1 when a download failed (the application then runs on the CPU).
"""
import glob
import hashlib
import os
import sys
import urllib.request
import zipfile

import paths

CUDA_DIR = os.path.join(paths.DATA_DIR, "cuda")
MARKER = os.path.join(CUDA_DIR, "installed.txt")
PYPI = "https://files.pythonhosted.org/packages"
WHEELS = [
    (f"{PYPI}/20/e2/fc9a0e985249d873150276d5afb02e39a66817fedbf1a385724393e505ed/"
     "nvidia_cublas_cu12-12.9.2.10-py3-none-win_amd64.whl",
     "623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661"),
    (f"{PYPI}/c7/bd/1d6709d2223e99f04079f16005f8ae6e11a14ee16b5eab6833686cf72fe1/"
     "nvidia_cudnn_cu12-9.28.1.4-py3-none-win_amd64.whl",
     "3467aafa9b260e6adf5fbbfc0e21d180133305b42032aa1160be2d3142bb8b09"),
    (f"{PYPI}/52/de/823919be3b9d0ccbf1f784035423c5f18f4267fb0123558d58b813c6ec86/"
     "nvidia_cuda_nvrtc_cu12-12.9.86-py3-none-win_amd64.whl",
     "72972ebdcf504d69462d3bcd67e7b81edd25d0fb85a2c46d3ea3517666636349"),
]
EXPECTED = "\n".join(url.rsplit("/", 1)[1] for url, _ in WHEELS) + "\n"


def has_nvidia_driver() -> bool:
    system = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    return os.name == "nt" and os.path.isfile(os.path.join(system, "nvcuda.dll"))


def _pip_dll_dirs() -> list[str]:
    """bin folders of nvidia-* wheels installed by pip (source checkout or venv)."""
    roots = [os.path.join(sys.prefix, "Lib", "site-packages"), *sys.path]
    found = []
    for root in roots:
        for bin_dir in glob.glob(os.path.join(root or ".", "nvidia", "*", "bin")):
            if os.path.normcase(os.path.abspath(bin_dir)) not in map(os.path.normcase, found):
                found.append(os.path.abspath(bin_dir))
    return found


def is_downloaded() -> bool:
    try:
        with open(MARKER, encoding="utf-8") as marker:
            return marker.read() == EXPECTED
    except OSError:
        return False


def needed() -> bool:
    """True when this NVIDIA computer still lacks the CUDA libraries."""
    return has_nvidia_driver() and not _pip_dll_dirs() and not is_downloaded()


def dll_dirs() -> list[str]:
    dirs = _pip_dll_dirs()
    if is_downloaded():
        dirs += sorted(glob.glob(os.path.join(CUDA_DIR, "*", "bin")))
    return dirs


def _download(url: str, sha256: str, target: str) -> None:
    name = url.rsplit("/", 1)[1]
    partial = target + ".partial"
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as response, open(partial, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = reported = 0
        while chunk := response.read(1 << 20):
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if done - reported >= 100 << 20:
                reported = done
                print(f"  {done >> 20} of {total >> 20} MB", flush=True)
    if digest.hexdigest() != sha256:
        os.remove(partial)
        raise RuntimeError(f"{name}: checksum mismatch, download discarded")
    os.replace(partial, target)


def _extract_dlls(wheel: str) -> None:
    """Keeps nvidia/<package>/bin/*.dll as CUDA_DIR/<package>/bin/*.dll."""
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            parts = member.filename.split("/")
            if (len(parts) == 4 and parts[0] == "nvidia" and parts[2] == "bin"
                    and parts[3].lower().endswith(".dll")):
                target_dir = os.path.join(CUDA_DIR, parts[1], "bin")
                os.makedirs(target_dir, exist_ok=True)
                with archive.open(member) as source, \
                        open(os.path.join(target_dir, parts[3]), "wb") as target:
                    while chunk := source.read(1 << 20):
                        target.write(chunk)


def install() -> None:
    os.makedirs(CUDA_DIR, exist_ok=True)
    if os.path.exists(MARKER):
        os.remove(MARKER)
    print("NVIDIA graphics card found: downloading its CUDA libraries once (about 1.3 GB).",
          flush=True)
    for url, sha256 in WHEELS:
        name = url.rsplit("/", 1)[1]
        print(f"{name}...", flush=True)
        wheel = os.path.join(CUDA_DIR, name)
        _download(url, sha256, wheel)
        _extract_dlls(wheel)
        os.remove(wheel)
    with open(MARKER, "w", encoding="utf-8") as marker:
        marker.write(EXPECTED)
    print("CUDA libraries ready.", flush=True)


if __name__ == "__main__":
    if not needed():
        sys.exit(0)
    try:
        install()
    except Exception as error:
        print(f"CUDA download failed ({error}); the application will use the CPU.", flush=True)
        sys.exit(1)
