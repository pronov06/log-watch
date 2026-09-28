"""
Publisher dispatcher — async queue worker that routes alerts to all configured publishers.

Features:
- Drains the queue in small batches so CloudWatch gets one PutLogEvents per burst
- Retry with exponential backoff + jitter on any publisher exception
- A failed publisher NEVER crashes the pipeline or blocks the UI
- Per-alert publish_status is pushed back to the bus (`alert_update`) so the UI shows it
- shutdown() drains whatever is still queued before the process exits
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

from app.config import Settings
from app.models import Alert
from app.publishers.console import ConsolePublisher
from app.publishers.cloudwatch import CloudWatchPublisher
from app.publishers.sns import SnsPublisher

logger = logging.getLogger(__name__)

MAX_BATCH = 50


class Dispatcher:
    """
    Consumes alerts from a queue and dispatches them to all configured publishers.

    Runs as a background asyncio task. Failures are logged and tracked in
    publish_status, but never propagate.
    """

    def __init__(self, cfg: Settings, alert_queue: asyncio.Queue, bus=None):
        self.cfg = cfg
        self.alert_queue = alert_queue
        self.bus = bus
        self.publishers: list[tuple[str, object]] = []
        self.max_retries = cfg.publish_max_retries
        self.backoff_base = cfg.publish_backoff_base_sec
        self._running = False

        # Health stats
        self.published = 0
        self.failures = 0
        self.last_error: str | None = None
        self.last_ok_at: float | None = None

        self._setup_publishers()

    def _setup_publishers(self) -> None:
        """Configure publishers based on PUBLISH_MODE."""
        # Console publisher is always active
        self.publishers.append(("console", ConsolePublisher()))

        if self.cfg.publish_mode == "aws":
            self.publishers.append(("cloudwatch", CloudWatchPublisher(
                log_group=self.cfg.cw_log_group,
                log_stream=self.cfg.cw_log_stream,
                region=self.cfg.aws_region,
                endpoint_url=self.cfg.aws_endpoint_url,
            )))
            if self.cfg.sns_topic_arn:
                self.publishers.append(("sns", SnsPublisher(
                    topic_arn=self.cfg.sns_topic_arn,
                    region=self.cfg.aws_region,
                    min_severity=self.cfg.sns_min_severity,
                    endpoint_url=self.cfg.aws_endpoint_url,
                )))

        names = [name for name, _ in self.publishers]
        logger.info("Dispatcher configured with publishers: %s", names)

    async def run(self) -> None:
        """Main worker loop — consume alerts and dispatch."""
        self._running = True
        logger.info("Dispatcher started")

        while self._running:
            try:
                first: Alert = await asyncio.wait_for(self.alert_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            batch = [first]
            while len(batch) < MAX_BATCH and not self.alert_queue.empty():
                batch.append(self.alert_queue.get_nowait())
            await self._dispatch(batch)

    async def shutdown(self, timeout: float = 5.0) -> None:
        """Stop accepting work and flush anything still queued (bounded by timeout)."""
        self._running = False
        pending: list[Alert] = []
        while not self.alert_queue.empty():
            pending.append(self.alert_queue.get_nowait())
        if not pending:
            return
        logger.info("Dispatcher flushing %d queued alert(s) before exit", len(pending))
        try:
            await asyncio.wait_for(self._dispatch(pending), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error("Dispatcher flush timed out; %d alert(s) may be unpublished", len(pending))

    async def _dispatch(self, alerts: list[Alert]) -> None:
        """Send alerts to every publisher; batch-capable publishers get one call."""
        statuses: dict[str, dict[str, str]] = {a.id + a.event: {} for a in alerts}

        for name, publisher in self.publishers:
            if hasattr(publisher, "publish_batch"):
                result = await self._with_retry(name, lambda p=publisher: p.publish_batch(alerts))
                for a in alerts:
                    statuses[a.id + a.event][name] = result
            else:
                for a in alerts:
                    result = await self._with_retry(name, lambda p=publisher, a=a: p.publish(a))
                    statuses[a.id + a.event][name] = result

        for a in alerts:
            a.publish_status = statuses[a.id + a.event]
            if self.bus is not None:
                self.bus.update_alert(a.id, {"publish_status": a.publish_status})
            logger.debug("Publish status for %s: %s", a.id[:8], a.publish_status)

    async def _with_retry(self, name: str, call) -> str:
        """Run a publisher call with exponential backoff and full jitter."""
        for attempt in range(self.max_retries):
            try:
                result = await call()
                if result == "ok":
                    self.published += 1
                    self.last_ok_at = time.time()
                return result
            except Exception as exc:
                self.failures += 1
                self.last_error = f"{name}: {exc}"[:200]
                if attempt < self.max_retries - 1:
                    delay = self.backoff_base * (2 ** attempt) * random.uniform(0.5, 1.5)
                    logger.warning("%s publish attempt %d failed, retrying in %.1fs: %s",
                                   name, attempt + 1, delay, exc)
                    await asyncio.sleep(delay)
                else:
                    logger.error("%s publish failed after %d attempts: %s",
                                 name, self.max_retries, exc)
        return "failed"

    def stop(self) -> None:
        """Signal the dispatcher to stop."""
        self._running = False

    def stats(self) -> dict:
        return {
            "publishers": [name for name, _ in self.publishers],
            "published": self.published,
            "failures": self.failures,
            "last_error": self.last_error,
            "last_ok_at": self.last_ok_at,
            "queued": self.alert_queue.qsize(),
        }
