"""
Publisher dispatcher — async queue worker that routes alerts to all configured publishers.

Features:
- asyncio.Queue consumption with a single worker task
- Retry with exponential backoff (3 attempts: 1s, 2s, 4s) on throttling/network errors
- A failed publisher NEVER crashes the pipeline or blocks the UI
- Each alert gets a publish_status field shown in the UI
"""

from __future__ import annotations

import asyncio
import logging

from app.config import Settings
from app.models import Alert
from app.publishers.console import ConsolePublisher
from app.publishers.cloudwatch import CloudWatchPublisher
from app.publishers.sns import SnsPublisher

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE = 1.0  # seconds


class Dispatcher:
    """
    Consumes alerts from a queue and dispatches them to all configured publishers.

    Runs as a background asyncio task. Failures are logged and tracked in
    publish_status, but never propagate.
    """

    def __init__(self, cfg: Settings, alert_queue: asyncio.Queue):
        self.cfg = cfg
        self.alert_queue = alert_queue
        self.publishers: list[tuple[str, object]] = []
        self.publish_failures: int = 0
        self._running = False

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
                alert: Alert = await asyncio.wait_for(
                    self.alert_queue.get(), timeout=5.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            await self._dispatch(alert)

    async def _dispatch(self, alert: Alert) -> None:
        """Send an alert to all publishers with retry."""
        status: dict[str, str] = {}

        for name, publisher in self.publishers:
            result = await self._publish_with_retry(name, publisher, alert)
            status[name] = result

        alert.publish_status = status
        logger.debug("Publish status for %s: %s", alert.id[:8], status)

    async def _publish_with_retry(self, name: str, publisher, alert: Alert) -> str:
        """Attempt to publish with exponential backoff retries."""
        for attempt in range(MAX_RETRIES):
            try:
                result = await publisher.publish(alert)
                return result
            except Exception as exc:
                self.publish_failures += 1
                if attempt < MAX_RETRIES - 1:
                    delay = BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "%s publish attempt %d failed, retrying in %.1fs: %s",
                        name, attempt + 1, delay, exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "%s publish failed after %d attempts: %s",
                        name, MAX_RETRIES, exc,
                    )
                    return "failed"

        return "failed"

    def stop(self) -> None:
        """Signal the dispatcher to stop."""
        self._running = False
