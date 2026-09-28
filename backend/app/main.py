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
from app.publishers.metrics import MetricsReporter

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
    dispatcher = Dispatcher(cfg, pipeline.alert_queue, bus=bus)
    app.state.dispatcher = dispatcher
    dispatcher_task = asyncio.create_task(dispatcher.run(), name="dispatcher")

    reporter: MetricsReporter | None = None
    reporter_task = None
    if cfg.publish_mode == "aws" and cfg.cw_metrics_enabled:
        reporter = MetricsReporter(
            region=cfg.aws_region,
            endpoint_url=cfg.aws_endpoint_url,
            interval_sec=cfg.cw_metrics_interval_sec,
            open_alerts=lambda: len(pipeline.alert_manager.get_active_alerts()),
        )
        pipeline.metric_listeners.append(reporter.add)
        reporter_task = asyncio.create_task(reporter.run(), name="cw_metrics")
    app.state.metrics_reporter = reporter

    logger.info("=" * 60)
    logger.info("  Log Anomaly Detector started")
    logger.info("  Tailing: %s", cfg.log_file_path)
    logger.info("  Publish mode: %s", cfg.publish_mode)
    logger.info("  Dashboard: http://localhost:5173")
    logger.info("  API: http://localhost:8000/api/health")
    logger.info("=" * 60)

    yield

    # Shutdown: stop producers first, then flush consumers so no alert is lost.
    logger.info("Shutting down...")
    await pipeline.stop()
    dispatcher.stop()
    await asyncio.gather(dispatcher_task, return_exceptions=True)
    await dispatcher.shutdown(timeout=5.0)
    if reporter is not None:
        reporter.stop()
        reporter_task.cancel()
        await reporter.flush()
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
