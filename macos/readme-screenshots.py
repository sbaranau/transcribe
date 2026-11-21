"""README screenshots on macOS: runs the installed Live Transcription (v1.35 or later) with demo
data (a demo microphone name, demo recent results, an English demo recording) in English and the
light theme, and captures four screens with screencapture into ~/Desktop/live-transcription-shots.
Nothing is saved to the app's settings or its recent list."""
import math
import os
import subprocess
import sys
import time

RES = "/Applications/Live Transcription.app/Contents/Resources"
APP = os.path.join(RES, "app")
DATA = os.path.expanduser("~/Library/Application Support/Live Transcription")
OUT = os.path.expanduser("~/Desktop/live-transcription-shots")
DEMO = os.path.join(OUT, "demo")
os.makedirs(DEMO, exist_ok=True)
os.environ.update(TRANSCRIBE_DATA_DIR=DATA, TRANSCRIBE_CONFIG_DIR=DATA, HF_HOME=os.path.join(DATA, "huggingface"),
                  TRANSCRIBE_VERSION_FILE=os.path.join(RES, "VERSION"), HF_HUB_DISABLE_SYMLINKS_WARNING="1",
                  TRANSCRIBE_THEME="light")

# An English demo recording, spoken by macOS.
WAV = os.path.join(DEMO, "Team meeting.wav")
if not os.path.exists(WAV):
    text = ("Good morning everyone. Let us start with the status of the release. The installer is now much "
            "smaller. Next week we want to finish the new home screen. Anna will prepare the screenshots for "
            "the documentation by Friday. Are there any questions? Then let us talk about the budget for next "
            "quarter. We agreed to keep it at the same level as this year. Thank you all, see you on Monday. ")
    subprocess.run(["say", "-o", WAV, "--file-format=WAVE", "--data-format=LEI16@16000", text * 2], check=True)

sys.path.insert(0, APP)
os.chdir(APP)
import ui_text  # noqa: E402
ui_text.set_language("en")
import live  # noqa: E402
import live_gui  # noqa: E402
import transcribe  # noqa: E402


class Device:
    def __init__(self, name):
        self.name, self.id = name, name


MICS = [Device("MacBook Air Microphone"), Device("USB headset")]
live.list_devices = lambda: (MICS, MICS[0], [])  # macOS: no computer sound without a loopback device


class FakeProbe:
    def __init__(self, microphone, speakers):
        self.microphone, self.computer = microphone, list(speakers)

    def levels(self):
        return 0.05 + 0.04 * math.sin(time.time() * 3), 0.0

    def stop(self):
        pass


live.LevelProbe = FakeProbe
SETTINGS = {"live": {"language": "en", "translate": "de", "folder": os.path.expanduser("~/Documents/Meetings")},
            "after": {"split": "1", "count": "0", "translate": "1", "target": "de"}}
live_gui.App.load_ui_settings = staticmethod(lambda section="live": dict(SETTINGS.get(section, {})))
live_gui.App.save_ui_settings = staticmethod(lambda values, section="live": None)
live_gui.add_recent = lambda *args: None
recent = []
for kind, name, folder in [("file", "Customer interview.mp4", "Customer interview"),
                           ("live", "2026-11-19 10-02-11", "2026-11-19 10-02-11"),
                           ("file", "Team meeting.wav", "Team meeting")]:
    os.makedirs(os.path.join(DEMO, folder), exist_ok=True)
    recent.append({"kind": kind, "name": name, "folder": os.path.join(DEMO, folder), "date": "19.11.2026 14:29"})
live_gui.load_recent = lambda: recent
live_gui.notify = lambda *args: None

original = live_gui.App.__init__


def init(self, *args, **kwargs):
    original(self, *args, **kwargs)
    root = self.root
    root.attributes("-topmost", True)

    def shot(name):
        """The window with its title bar (about 28 points above the content on macOS)."""
        root.lift()
        root.update()
        x, y, w, h = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
        subprocess.Popen(["screencapture", "-x", "-R", f"{x},{y - 28},{w},{h + 28}", os.path.join(OUT, name)])
        print("captured", name, flush=True)

    def home():
        root.geometry("900x720+80+60")
        root.after(2500, lambda: shot("1-home.png"))
        root.after(4000, setup)

    def setup():
        self.show_live_setup()
        wait_model()

    def wait_model():
        if self.model is None or self.translation_loading:
            root.after(500, wait_model)
            return
        root.geometry("900x680+80+60")
        root.after(3000, lambda: shot("2-before.png"))
        root.after(5000, files)

    def files():
        self.stop_probe()
        self.open_files([WAV])
        root.after(5000, run)

    def run():
        root.geometry("900x600+80+60")
        self.run_processing()
        for delay in (5000, 8000, 11000):
            root.after(delay, lambda d=delay: shot(f"3-processing-{d // 1000}s.png"))
        wait_done()

    def wait_done():
        if self.processing is not None:
            root.after(1000, wait_done)
            return
        root.after(2500, lambda: shot("4-results.png"))
        root.after(5000, root.destroy)

    root.after(3000, home)


live_gui.App.__init__ = init
sys.argv = ["transcribe.py", "--live", "--cpu"]
transcribe.main()
print("Done:", OUT)
