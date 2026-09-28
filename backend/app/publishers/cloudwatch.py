"""
CloudWatch Logs publisher — pushes structured alert JSON to a CloudWatch log stream.

Each alert is a single JSON message, queryable with CloudWatch Logs Insights:
  fields @timestamp, severity, title, error_rate
  | filter severity in ["HIGH","CRITICAL"]
  | sort @timestamp desc

Failures are raised (not swallowed) so the Dispatcher can retry with backoff.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from app.models import Alert
from app.publishers.aws import make_client

logger = logging.getLogger(__name__)

# PutLogEvents hard limits: 10,000 events and 1,048,576 bytes per call, where each
# event costs len(utf8 message) + 26 bytes.
MAX_BATCH_EVENTS = 10_000
MAX_BATCH_BYTES = 1_048_576
EVENT_OVERHEAD_BYTES = 26


def alert_to_message(alert: Alert) -> str:
    return json.dumps({
        "service": "log-anomaly-detector",
        "event": alert.event,
        "severity": alert.severity,
        "peak_severity": alert.peak_severity,
        "alert_id": alert.id,
        "key": alert.key,
        "title": alert.title,
        "error_rate": alert.error_rate,
        "baseline_mean": alert.baseline_mean,
        "z_score": alert.z_score,
        "window_seconds": alert.window_seconds,
        "window_total": alert.window_total,
        "window_errors": alert.window_errors,
        "top_errors": alert.top_errors,
        "opened_at": alert.opened_at,
        "resolved_at": alert.resolved_at,
    }, default=str)


def chunk_events(events: list[dict]) -> list[list[dict]]:
    """Split log events into batches that respect PutLogEvents count and byte limits."""
    batches: list[list[dict]] = []
    current: list[dict] = []
    size = 0
    for ev in sorted(events, key=lambda e: e["timestamp"]):
        ev_size = len(ev["message"].encode("utf-8")) + EVENT_OVERHEAD_BYTES
        if current and (len(current) >= MAX_BATCH_EVENTS or size + ev_size > MAX_BATCH_BYTES):
            batches.append(current)
            current, size = [], 0
        current.append(ev)
        size += ev_size
    if current:
        batches.append(current)
    return batches


class CloudWatchPublisher:
    """Publishes alerts to AWS CloudWatch Logs."""

    def __init__(self, log_group: str, log_stream: str, region: str, endpoint_url: str = ""):
        self.log_group = log_group
        self.log_stream = log_stream
        self.region = region
        self.endpoint_url = endpoint_url or None
        self._client = None
        self._ensured = False

    def _get_client(self):
        if self._client is None:
            self._client = make_client("logs", self.region, self.endpoint_url)
        return self._client

    def _ensure_destination(self) -> None:
        """Create the log group/stream if missing. Retried on the next publish if it fails."""
        client = self._get_client()
        for create, kwargs in (
            (client.create_log_group, {"logGroupName": self.log_group}),
            (client.create_log_stream, {"logGroupName": self.log_group, "logStreamName": self.log_stream}),
        ):
            try:
                create(**kwargs)
            except client.exceptions.ResourceAlreadyExistsException:
                pass
        self._ensured = True

    def _put_batches(self, alerts: list[Alert]) -> None:
        """Blocking boto3 work; always called via asyncio.to_thread."""
        if not self._ensured:
            self._ensure_destination()
        client = self._get_client()
        now_ms = int(time.time() * 1000)
        events = [{"timestamp": now_ms, "message": alert_to_message(a)} for a in alerts]
        for batch in chunk_events(events):
            try:
                client.put_log_events(
                    logGroupName=self.log_group, logStreamName=self.log_stream, logEvents=batch,
                )
            except client.exceptions.ResourceNotFoundException:
                # Group/stream deleted underneath us: recreate once, then retry the batch.
                self._ensure_destination()
                client.put_log_events(
                    logGroupName=self.log_group, logStreamName=self.log_stream, logEvents=batch,
                )

    async def publish_batch(self, alerts: list[Alert]) -> str:
        """Push alerts as structured JSON log events. Raises on failure."""
        if not alerts:
            return "skipped"
        await asyncio.to_thread(self._put_batches, alerts)
        logger.info("CloudWatch: published %d alert event(s)", len(alerts))
        return "ok"

    async def publish(self, alert: Alert) -> str:
        return await self.publish_batch([alert])
