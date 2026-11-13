# Third-party components

This repository contains only the tool's own code (MIT, see [LICENSE](../LICENSE)). Nothing below
is included in it: the setup downloads the packages from PyPI and the models from Hugging Face and
GitHub onto each computer, each under its own license.

## Models

| Model | Used for | Source | License |
|---|---|---|---|
| Whisper large-v3-turbo (OpenAI), CTranslate2 conversion | speech recognition | [mobiuslabsgmbh/faster-whisper-large-v3-turbo](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo) | MIT |
| pyannote segmentation 3.0 | voice separation: who speaks when | [sherpa-onnx releases](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-segmentation-models) | MIT |
| NVIDIA NeMo TitaNet-small | voice separation: voice embeddings | [sherpa-onnx releases](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models) | CC-BY-4.0 |
| Opus-MT ru-en, en-de (Helsinki-NLP), ONNX export | translation | [Xenova/opus-mt-ru-en](https://huggingface.co/Xenova/opus-mt-ru-en), [Xenova/opus-mt-en-de](https://huggingface.co/Xenova/opus-mt-en-de) | CC-BY-4.0 |
| Opus-MT en-ru, de-en (Helsinki-NLP), ONNX export | translation | [Xenova/opus-mt-en-ru](https://huggingface.co/Xenova/opus-mt-en-ru), [Xenova/opus-mt-de-en](https://huggingface.co/Xenova/opus-mt-de-en) | Apache-2.0 |

Opus-MT: Jörg Tiedemann and Santhosh Thottingal, "OPUS-MT — Building open translation services
for the World", EAMT 2020; University of Helsinki, [Helsinki-NLP/Opus-MT](https://github.com/Helsinki-NLP/Opus-MT).

## Python packages (app/requirements.txt)

| Package | Used for | License |
|---|---|---|
| faster-whisper, CTranslate2 | running Whisper on the GPU or CPU | MIT |
| PyAV (av) | reading audio and video files; its wheels bundle FFmpeg libraries (LGPL) | BSD-3-Clause |
| nvidia-cublas-cu12, nvidia-cudnn-cu12 | CUDA libraries for the GPU | NVIDIA software license |
| sherpa-onnx | voice separation | Apache-2.0 |
| onnxruntime | running the ONNX models | MIT |
| tokenizers, huggingface-hub | translation tokenizer; model download | Apache-2.0 |
| soundcard, cffi | recording the microphone and the computer sound | BSD-3-Clause, MIT |
| numpy | audio and model arithmetic | BSD-3-Clause |

The setup installs Python 3.12 (PSF license) with [uv](https://docs.astral.sh/uv/) (MIT or
Apache-2.0). The optional AI tools for the check and the summary (Claude Code, the OpenAI Codex
CLI, Ollama, LM Studio) are not installed by this tool and are used under their own terms.
