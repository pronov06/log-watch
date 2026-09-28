"""
FastAPI application factory with lifespan management.

The lifespan context manager starts the pipeline and dispatcher tasks
on startup and shuts them down cleanly on shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.api.ws import router as ws_router
from app.bus import EventBus
from app.config import Settings, get_settings
from app.pipeline import Pipeline
from app.publishers.dispatcher import Dispatcher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start pipeline and dispatcher on startup, stop on shutdown."""
    cfg: Settings = app.state.cfg
    bus: EventBus = app.state.bus
    pipeline: Pipeline = app.state.pipeline

    # Ensure the data directory exists
    Path(cfg.log_file_path).parent.mkdir(parents=True, exist_ok=True)

    # Start the pipeline
    await pipeline.start()

    # Start the publisher dispatcher
    dispatcher = Dispatcher(cfg, pipeline.alert_queue)
    app.state.dispatcher = dispatcher
    dispatcher_task = asyncio.create_task(dispatcher.run(), name="dispatcher")

    logger.info("=" * 60)
    logger.info("  Log Anomaly Detector started")
    logger.info("  Tailing: %s", cfg.log_file_path)
    logger.info("  Publish mode: %s", cfg.publish_mode)
    logger.info("  Dashboard: http://localhost:5173")
    logger.info("  API: http://localhost:8000/api/health")
    logger.info("=" * 60)

    yield

    # Shutdown
    logger.info("Shutting down...")
    dispatcher.stop()
    dispatcher_task.cancel()
    await pipeline.stop()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    cfg = get_settings()

    app = FastAPI(
        title="Log Anomaly Detector",
        description="Real-time log anomaly detection with alert feed",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Store shared state
    app.state.cfg = cfg
    app.state.bus = EventBus(ring_size=cfg.ring_buffer_size)
    app.state.pipeline = Pipeline(cfg, app.state.bus)
    app.state.start_time = time.time()

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    app.include_router(api_router)
    app.include_router(ws_router)

    return app


# For `uvicorn app.main:app`
app = create_app()
