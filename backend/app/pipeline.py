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
from collections import deque


from app.alerts import AlertManager
from app.baseline import make_baseline
from app.bus import EventBus
from app.config import Settings
from app.detector import Detector
from app.evaluator import Evaluator
from app.parser import parse_line
from app.tailer import MultiTailer
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
        self.baseline = make_baseline(cfg)
        self.detector = Detector(cfg)
        self.alert_manager = AlertManager(cfg, window_seconds=cfg.window_seconds)
        # Fast window (dual-window detection) keeps its own baseline: a 60 s rate is noisier
        self.fast_baseline = make_baseline(cfg, ".fast") if cfg.fast_window_seconds else None
        self.evaluator = Evaluator(cfg, self.window, self.baseline, self.detector, self.alert_manager,
                                   fast_baseline=self.fast_baseline)

        # Tailer → parser queue
        self._line_queue: asyncio.Queue = asyncio.Queue(maxsize=10_000)
        self.tailer = MultiTailer(
            patterns=cfg.source_patterns,
            queue=self._line_queue,
            poll_interval=cfg.tail_poll_interval_sec,
            rescan_interval=cfg.source_rescan_sec,
        )

        # Tasks
        self._tasks: list[asyncio.Task] = []
        self._running = False

        # Latency instrumentation (RT2).
        # Ingest lag = processing time - the event's own timestamp, i.e. how long a line
        # took from being logged to entering the window (includes the tailer poll interval).
        self._lags: deque[float] = deque(maxlen=2000)

        # Log sampling state
        self._log_counter = 0
        self._last_log_emit = 0.0

        # Publisher queue (filled by the pipeline, consumed by the dispatcher)
        self.alert_queue: asyncio.Queue = asyncio.Queue(maxsize=500)

        # Synchronous hooks called with every metric point (e.g. CloudWatch metrics buffer)
        self.metric_listeners: list = []

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
        self._save_baselines()
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

            lag = time.time() - event.ts.timestamp()
            if 0 <= lag < 3600:  # ignore replayed history and skewed/naive local clocks
                self._lags.append(lag)

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
                tick = self.evaluator.step(time.time())
                tick.metric["ingest_lag_ms_p95"] = self._lag_pct(0.95)

                self.bus.publish("metric", tick.metric)
                for listener in self.metric_listeners:
                    listener(tick.metric)
                self.bus.publish("baseline", tick.baseline_state)

                for alert_event in tick.alerts:
                    self.bus.publish("alert", alert_event.model_dump())
                    try:
                        self.alert_queue.put_nowait(alert_event)
                    except asyncio.QueueFull:
                        logger.warning("Publisher queue full, dropping alert")

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Evaluator error")

    def _save_baselines(self) -> None:
        self.baseline.save()
        if self.fast_baseline is not None:
            self.fast_baseline.save()

    def _lag_pct(self, q: float) -> float | None:
        if not self._lags:
            return None
        ordered = sorted(self._lags)
        return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))] * 1000, 1)

    def latency_stats(self) -> dict:
        cfg = self.cfg
        return {
            "ingest_lag_ms_p50": self._lag_pct(0.50),
            "ingest_lag_ms_p95": self._lag_pct(0.95),
            "last_detection_latency_sec": self.evaluator.last_detect_sec,
            # Worst case from a sustained breach to OPENED on the wire
            "detection_budget_sec": round(cfg.eval_interval_sec * (cfg.confirm_ticks + 1) + 1, 1),
        }

    async def _baseline_persist_loop(self) -> None:
        """Save the baseline to disk every 60 seconds."""
        while self._running:
            await asyncio.sleep(60)
            try:
                self._save_baselines()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Baseline persist error")
