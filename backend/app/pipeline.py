"""
Pipeline — orchestrates the tailer → parser → window → baseline → detector → alerts loop.

This is the "engine room" of the anomaly detector. It runs as a set of cooperating
asyncio tasks within the FastAPI lifespan:

1. tailer_task: reads new lines from the log file, parses them, pushes to the window
2. evaluator_task: every EVAL_INTERVAL_SEC, computes the metric, updates the baseline,
   runs the detector, and emits events to the bus
3. log_sampler_task: samples parsed log lines and publishes them to the bus for the
   frontend log tail (rate-limited to ~10/sec)
4. baseline_persist_task: saves the baseline to disk every 60 seconds
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import Counter
from datetime import datetime, timezone

from app.alerts import AlertManager
from app.baseline import Baseline
from app.bus import EventBus
from app.config import Settings
from app.detector import Detector
from app.models import Severity
from app.parser import parse_line
from app.tailer import Tailer
from app.window import SlidingWindow

logger = logging.getLogger(__name__)

# Pattern to normalize error messages for grouping:
# Replace digits, UUIDs, and IPs with placeholders
_NORMALIZE_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"  # UUID
    r"|\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"  # IP
    r"|\b\d+\b",  # digits
    re.IGNORECASE,
)


def _normalize_message(msg: str) -> str:
    """Replace digits, UUIDs, and IPs with placeholders for grouping."""
    return _NORMALIZE_RE.sub("<N>", msg)


class Pipeline:
    """
    The main processing pipeline.

    Call start() to kick off all async tasks, stop() to shut them down.
    """

    def __init__(self, cfg: Settings, bus: EventBus):
        self.cfg = cfg
        self.bus = bus

        # Core components
        self.window = SlidingWindow(window_seconds=cfg.window_seconds)
        self.baseline = Baseline(
            warmup_samples=cfg.baseline_warmup_samples,
            alpha=cfg.baseline_alpha,
            min_std=cfg.baseline_min_std,
            z_low=cfg.z_low,
            persist_path="./data/baseline.json",
        )
        self.detector = Detector(cfg)
        self.alert_manager = AlertManager(cfg, window_seconds=cfg.window_seconds)

        # Tailer → parser queue
        self._line_queue: asyncio.Queue = asyncio.Queue(maxsize=10_000)
        self.tailer = Tailer(
            path=cfg.log_file_path,
            queue=self._line_queue,
            poll_interval=cfg.tail_poll_interval_sec,
            from_start=False,
        )

        # Tasks
        self._tasks: list[asyncio.Task] = []
        self._running = False

        # Log sampling state
        self._log_counter = 0
        self._last_log_emit = 0.0

        # Publisher queue (filled by the pipeline, consumed by the dispatcher)
        self.alert_queue: asyncio.Queue = asyncio.Queue(maxsize=500)

    async def start(self) -> None:
        """Start all pipeline tasks."""
        self._running = True
        self._tasks = [
            asyncio.create_task(self.tailer.run(), name="tailer"),
            asyncio.create_task(self._consumer_loop(), name="consumer"),
            asyncio.create_task(self._evaluator_loop(), name="evaluator"),
            asyncio.create_task(self._baseline_persist_loop(), name="baseline_persist"),
        ]
        logger.info("Pipeline started (%d tasks)", len(self._tasks))

    async def stop(self) -> None:
        """Stop all pipeline tasks."""
        self._running = False
        self.tailer.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self.baseline.save()
        logger.info("Pipeline stopped")

    async def _consumer_loop(self) -> None:
        """
        Consume parsed log lines from the tailer queue and feed them
        into the sliding window.

        Also samples log lines for the frontend log tail (rate-limited).
        """
        while self._running:
            try:
                line = await asyncio.wait_for(
                    self._line_queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            event = parse_line(line, fmt=self.cfg.log_format)
            if event is None:
                continue

            # Feed into the sliding window
            normalized_msg = _normalize_message(event.message) if event.level == "ERROR" else ""
            self.window.add(event.level, message=normalized_msg)

            # Sample log lines for the frontend (max ~10/sec, prioritize errors)
            now = time.time()
            is_error = event.level == "ERROR"
            should_emit = (
                is_error
                or (now - self._last_log_emit) >= 0.1  # max 10/sec
            )
            if should_emit:
                self._last_log_emit = now
                self.bus.publish("log", {
                    "ts": event.ts.isoformat().replace("+00:00", "Z"),
                    "level": event.level,
                    "service": event.service,
                    "message": event.message,
                    "raw": event.raw[:500],  # Cap raw line length
                })

    async def _evaluator_loop(self) -> None:
        """
        Every EVAL_INTERVAL_SEC:
        1. Snapshot the window
        2. Feed the baseline (warm-up or update)
        3. Run the detector
        4. Process alerts
        5. Emit metric + baseline + alert events to the bus
        """
        while self._running:
            await asyncio.sleep(self.cfg.eval_interval_sec)

            try:
                snap = self.window.snapshot()
                reliable = snap["total"] >= self.cfg.min_events_in_window

                # Baseline: warm-up or update
                if reliable and not self.baseline.ready:
                    self.baseline.warmup_add(snap["error_rate"])

                # Detection
                result = None
                if reliable and self.baseline.ready:
                    result = self.detector.evaluate(snap, self.baseline)

                # Update baseline (only if not breaching and no open alert)
                breaching = bool(result and result.severity > Severity.NONE)
                if (
                    reliable
                    and self.baseline.ready
                    and not breaching
                    and not self.alert_manager.has_open_alert()
                ):
                    self.baseline.update(snap["error_rate"])

                # Build metric point for the bus
                baseline_state = self.baseline.state()
                metric_data = {
                    "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "error_rate": round(snap["error_rate"], 6),
                    "total": snap["total"],
                    "errors": snap["errors"],
                    "events_per_sec": round(snap["events_per_sec"], 2),
                    "baseline_mean": baseline_state["mean"] if self.baseline.ready else None,
                    "baseline_std": baseline_state["std"] if self.baseline.ready else None,
                    "upper_band": baseline_state["upper_band"] if self.baseline.ready else None,
                    "lower_band": baseline_state["lower_band"] if self.baseline.ready else None,
                    "z": round(result.z, 4) if result else None,
                    "severity": result.severity.name if result else "NONE",
                }

                self.bus.publish("metric", metric_data)
                self.bus.publish("baseline", baseline_state)

                # Process alerts
                top_errors = self.window.top_errors(n=3)
                for alert_event in self.alert_manager.process(result, top_errors=top_errors):
                    alert_data = alert_event.model_dump()
                    self.bus.publish("alert", alert_data)
                    # Enqueue for publishers
                    try:
                        self.alert_queue.put_nowait(alert_event)
                    except asyncio.QueueFull:
                        logger.warning("Publisher queue full, dropping alert")

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Evaluator error")

    async def _baseline_persist_loop(self) -> None:
        """Save the baseline to disk every 60 seconds."""
        while self._running:
            await asyncio.sleep(60)
            try:
                self.baseline.save()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Baseline persist error")
