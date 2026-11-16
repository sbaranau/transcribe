"""First-run installer for packaged desktop applications: speech models and, on Windows
computers with an NVIDIA graphics card, the CUDA libraries (cuda_runtime.py)."""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk

import cuda_runtime
import paths


def models_ready() -> bool:
    return all(os.path.isfile(os.path.join(paths.MODELS_DIR, name)) for name in (
        "large-v3-turbo/model.bin",
        "diarization/sherpa-onnx-pyannote-segmentation-3-0/model.onnx",
        "diarization/nemo_en_titanet_small.onnx",
    ))


def first_setup(need_models: bool, need_cuda: bool) -> bool:
    """Downloads what is missing in one window. Returns False only when the models are still
    missing: without the CUDA libraries the application runs on the CPU."""
    sizes = []
    if need_models:
        sizes.append("the speech models (about 1.7 GB)")
    if need_cuda:
        sizes.append("the NVIDIA graphics card libraries (about 1.3 GB)")
    root = tk.Tk()
    root.title("Live Transcription — first setup")
    root.geometry("620x360")
    root.resizable(True, True)
    ttk.Label(root, text="Preparing Live Transcription", font=("TkDefaultFont", 17, "bold")) \
        .pack(anchor="w", padx=24, pady=(22, 6))
    ttk.Label(root, text=(f"Downloaded once: {' and '.join(sizes)}. "
                          "Keep this window open. Your recordings never leave this computer."),
              wraplength=570, justify="left").pack(anchor="w", padx=24, pady=(0, 14))
    progress = ttk.Progressbar(root, mode="indeterminate")
    progress.pack(fill="x", padx=24, pady=(0, 14))
    progress.start(12)
    log = tk.Text(root, height=10, state="disabled", wrap="word")
    log.pack(fill="both", expand=True, padx=24, pady=(0, 20))
    events: queue.Queue[tuple[str, object]] = queue.Queue()
    result = {"ok": False}

    def run(script: str) -> None:
        process = subprocess.Popen(
            [sys.executable, os.path.join(paths.APP_DIR, script)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert process.stdout is not None
        for line in process.stdout:
            events.put(("line", line))
        process.wait()

    def worker() -> None:
        if need_models:
            run("download_models.py")
        if need_cuda and models_ready():
            run("cuda_runtime.py")
        events.put(("done", models_ready()))

    def poll() -> None:
        try:
            while True:
                kind, value = events.get_nowait()
                if kind == "line":
                    log.configure(state="normal")
                    log.insert("end", str(value))
                    log.configure(state="disabled")
                    log.see("end")
                else:
                    result["ok"] = bool(value)
                    progress.stop()
                    if value:
                        root.destroy()
                    else:
                        ttk.Label(root, text="Download failed. Check the connection and start the app again.",
                                  foreground="#c62828").pack(padx=24, pady=(0, 16))
                    return
        except queue.Empty:
            pass
        root.after(100, poll)

    threading.Thread(target=worker, daemon=True).start()
    root.after(100, poll)
    root.mainloop()
    return result["ok"]


if __name__ == "__main__":
    need_models = not models_ready()
    need_cuda = cuda_runtime.needed()
    if (need_models or need_cuda) and not first_setup(need_models, need_cuda):
        raise SystemExit(1)
    args = [sys.executable, os.path.join(paths.APP_DIR, "transcribe.py"), *sys.argv[1:]]
    if os.name == "nt":
        # os.execv on Windows spawns a new process without quoting its arguments, which breaks
        # paths with spaces such as "...\Programs\Live Transcription"; subprocess quotes them.
        raise SystemExit(subprocess.call(args))
    os.execv(sys.executable, args)
