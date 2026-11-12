"""Downloads the models into app/models (called by the setup); files already there are kept.

- Whisper large-v3-turbo (faster-whisper format) from Hugging Face, about 1.6 GB, no login.
- Voice separation (speaker diarization) for sherpa-onnx, about 45 MB, from the sherpa-onnx
  releases on GitHub: pyannote segmentation 3.0 and the NVIDIA NeMo TitaNet-small voice
  embedding model.
"""
import os
import sys
import tarfile
import urllib.request

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(TOOL_DIR, "models")
WHISPER_REPO = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
WHISPER_DIR = os.path.join(MODELS_DIR, "large-v3-turbo")
DIARIZATION_DIR = os.path.join(MODELS_DIR, "diarization")
RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
SEGMENTATION_ARCHIVE = f"{RELEASES}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
SEGMENTATION_MODEL = os.path.join(DIARIZATION_DIR, "sherpa-onnx-pyannote-segmentation-3-0", "model.onnx")
# "recongition" is the real (misspelled) release tag.
EMBEDDING_URL = f"{RELEASES}/speaker-recongition-models/nemo_en_titanet_small.onnx"
EMBEDDING_MODEL = os.path.join(DIARIZATION_DIR, "nemo_en_titanet_small.onnx")


def download(url: str, target: str) -> None:
    partial = target + ".partial"
    with urllib.request.urlopen(url, timeout=60) as response, open(partial, "wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
    os.replace(partial, target)


def whisper() -> None:
    if os.path.isfile(os.path.join(WHISPER_DIR, "model.bin")):
        print("Whisper model already present.")
        return
    print("Whisper model large-v3-turbo (about 1.6 GB)...", flush=True)
    from huggingface_hub import snapshot_download
    snapshot_download(WHISPER_REPO, local_dir=WHISPER_DIR)


def diarization() -> None:
    os.makedirs(DIARIZATION_DIR, exist_ok=True)
    if os.path.isfile(SEGMENTATION_MODEL):
        print("Voice segmentation model already present.")
    else:
        print("Voice segmentation model (7 MB)...", flush=True)
        archive = os.path.join(DIARIZATION_DIR, "segmentation.tar.bz2")
        download(SEGMENTATION_ARCHIVE, archive)
        with tarfile.open(archive) as tar:
            tar.extractall(DIARIZATION_DIR, filter="data")
        os.remove(archive)
    if os.path.isfile(EMBEDDING_MODEL):
        print("Voice embedding model already present.")
    else:
        print("Voice embedding model (38 MB)...", flush=True)
        download(EMBEDDING_URL, EMBEDDING_MODEL)


if __name__ == "__main__":
    whisper()
    diarization()
    sys.exit(0 if os.path.isfile(SEGMENTATION_MODEL) and os.path.isfile(EMBEDDING_MODEL) else 1)
