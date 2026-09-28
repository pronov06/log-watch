"""
Log Watch on a free Hugging Face Space (Gradio SDK).

Docker Spaces are a paid option, so this runs the same stack from Python instead:
- starts the traffic generator as a subprocess (writes a realistic, growing log file)
- runs the real FastAPI backend (tailer → detector → alerts → WebSocket) on port 7860
- serves the prebuilt React dashboard from the same origin at "/"

A small Gradio page is mounted at /gradio only because the Gradio SDK expects Gradio.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

os.environ.setdefault("LOG_FILE_PATH", str(DATA / "app.log"))
os.environ.setdefault("BASELINE_PATH", str(DATA / "baseline.json"))
os.environ.setdefault("PUBLISH_MODE", "dry_run")
os.environ.setdefault("ENABLE_SIM", "true")
os.environ.setdefault("LOG_JSON", "true")
os.environ.pop("STATIC_DIR", None)  # the dashboard is mounted below, after Gradio

sys.path.insert(0, str(ROOT / "backend"))

import gradio as gr  # noqa: E402
import uvicorn  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.main import create_app  # noqa: E402

GENERATOR = [
    sys.executable, "-m", "simulator.generate_logs",
    "--file", os.environ["LOG_FILE_PATH"], "--rps", "25", "--base-error", "0.02",
]

with gr.Blocks(title="Log Watch") as status_page:
    gr.Markdown("## Log Watch is running\nThe live dashboard is at the root of this Space: [open it](/).")


def build():
    api = create_app()
    api = gr.mount_gradio_app(api, status_page, path="/gradio")
    # Mounted last so /api, /ws and /gradio keep priority
    api.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="dashboard")
    return api


if __name__ == "__main__":
    generator = subprocess.Popen(GENERATOR, cwd=ROOT / "backend")
    try:
        uvicorn.run(build(), host="0.0.0.0", port=int(os.environ.get("PORT", "7860")))
    finally:
        generator.terminate()
