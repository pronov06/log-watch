"""
Log Watch on a free Hugging Face Space (Gradio SDK, ZeroGPU hardware).

Docker Spaces are paid, and on ZeroGPU only Gradio's own `launch()` may own port 7860,
so the stack runs *inside* Gradio's server:
- Gradio launches the web server on the port the Space runtime gives it
- our backend's lifespan (tailer → detector → alerts → publisher) is passed to Gradio,
  which runs it alongside its own startup and shutdown
- our /api and /ws routes plus the prebuilt React dashboard (/ and /assets) are placed
  in front of Gradio's routes; Gradio's internal endpoints keep working behind them
- the traffic generator runs as a subprocess, appending to the log file we tail
"""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
STATIC = ROOT / "static"

os.environ.setdefault("LOG_FILE_PATH", str(DATA / "app.log"))
os.environ.setdefault("BASELINE_PATH", str(DATA / "baseline.json"))
os.environ.setdefault("PUBLISH_MODE", "dry_run")
os.environ.setdefault("ENABLE_SIM", "true")
os.environ.setdefault("LOG_JSON", "true")
os.environ.pop("STATIC_DIR", None)  # the dashboard is attached to Gradio's app below

sys.path.insert(0, str(ROOT / "backend"))

# ZeroGPU refuses to start unless at least one @spaces.GPU function exists. Log Watch
# needs no GPU: this placeholder is never called. `spaces` also hooks gr.Blocks.launch()
# to report startup, which is why we launch through Gradio.
try:
    import spaces

    @spaces.GPU
    def _zero_gpu_placeholder() -> None:
        return None
except ImportError:  # running locally, outside Hugging Face
    pass

import gradio as gr  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.routing import Mount, Route  # noqa: E402

from app.main import create_app, lifespan as backend_lifespan  # noqa: E402

GENERATOR = [
    sys.executable, "-m", "simulator.generate_logs",
    "--file", os.environ["LOG_FILE_PATH"], "--rps", "25", "--base-error", "0.02",
]

backend = create_app()  # holds config, event bus and pipeline in backend.state


@asynccontextmanager
async def run_backend(_gradio_app):
    """Run our pipeline/dispatcher lifespan against *our* app object inside Gradio's server."""
    async with backend_lifespan(backend):
        yield


async def dashboard_index(_request):
    return FileResponse(STATIC / "index.html")


def attach_backend(gradio_app) -> None:
    """Put the Log Watch routes ahead of Gradio's own (first match wins in Starlette)."""
    # Everything the backend serves except FastAPI's auto docs. Newer FastAPI versions keep
    # included routers as nested router objects, so move route objects rather than paths.
    docs = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    ours = [r for r in backend.router.routes if getattr(r, "path", None) not in docs]
    ours += [
        Route("/", dashboard_index),
        Mount("/assets", app=StaticFiles(directory=STATIC / "assets"), name="dashboard-assets"),
    ]
    gradio_app.router.routes[0:0] = ours
    # Our routes read request.app.state (cfg, bus, pipeline, dispatcher, ready…), and inside
    # Gradio's server request.app is Gradio's app. The lifespan has already run by the time
    # launch() returns, so copy the backend's complete state across.
    for key, value in backend.state._state.items():
        setattr(gradio_app.state, key, value)


with gr.Blocks(title="Log Watch") as demo:
    gr.Markdown("## Log Watch\nThe live dashboard is served at the root of this Space.")


if __name__ == "__main__":
    generator = subprocess.Popen(GENERATOR, cwd=ROOT / "backend")
    try:
        demo.launch(
            server_name=os.environ.get("GRADIO_SERVER_NAME", "0.0.0.0"),
            app_kwargs={"lifespan": run_backend},
            # On Spaces, Gradio's server-side rendering puts a Node server on the public port
            # and proxies only Gradio's own paths to Python, so our dashboard and API would
            # never be reached. Without SSR, the Python server (with our routes) owns the port.
            ssr_mode=False,
            prevent_thread_lock=True,
        )
        attach_backend(demo.server_app)
        print("[log-watch] dashboard and API attached to the Gradio server", flush=True)
        demo.block_thread()
    finally:
        generator.terminate()
