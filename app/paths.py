"""Paths shared by the source checkout and the packaged macOS application.

In a checkout, data and settings stay beside the code for backwards compatibility. A packaged
application sets TRANSCRIBE_DATA_DIR and TRANSCRIBE_CONFIG_DIR so models and preferences survive
when the application bundle is replaced by an update.
"""
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_ROOT = os.path.dirname(APP_DIR)
DATA_DIR = os.environ.get("TRANSCRIBE_DATA_DIR", APP_DIR)
CONFIG_DIR = os.environ.get("TRANSCRIBE_CONFIG_DIR", APP_DIR)
MODELS_DIR = os.path.join(DATA_DIR, "models")


def config(name: str) -> str:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    return os.path.join(CONFIG_DIR, name)
