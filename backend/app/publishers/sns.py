"""
SNS publisher — sends alert notifications via AWS SNS.

Only publishes for OPENED, ESCALATED, and RESOLVED events when
severity >= SNS_MIN_SEVERITY. Subject is capped at 100 chars ASCII.
Failures are raised so the Dispatcher can retry with backoff.
"""

from __future__ import annotations

import asyncio
import json
import logging

from app.models import Alert
from app.publishers.aws import make_client

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


class SnsPublisher:
    """Publishes alerts to an AWS SNS topic."""

    def __init__(
        self,
        topic_arn: str,
        region: str,
        min_severity: str = "MEDIUM",
        endpoint_url: str = "",
    ):
        self.topic_arn = topic_arn
        self.region = region
        self.min_severity = min_severity
        self.endpoint_url = endpoint_url or None
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = make_client("sns", self.region, self.endpoint_url)
        return self._client

    async def publish(self, alert: Alert) -> str:
        """Publish alert notification to SNS."""
        # Only publish for actionable events
        if alert.event not in ("OPENED", "ESCALATED", "RESOLVED"):
            return "skipped"

        # RESOLVED is judged by the peak severity, so a LOW alert that was never
        # notified doesn't produce an orphan "resolved" email.
        sev = alert.peak_severity if alert.event == "RESOLVED" else alert.severity
        if _SEVERITY_ORDER.get(sev, 0) < _SEVERITY_ORDER.get(self.min_severity, 2):
            return "skipped"

        if not self.topic_arn:
            logger.warning("SNS topic ARN not configured, skipping")
            return "skipped"

        client = await asyncio.to_thread(self._get_client)

        # Subject: max 100 chars, ASCII only
        subject = f"[{alert.severity}] {alert.title}"[:100]

        # Human-readable message body
        body = (
            f"Alert: {alert.title}\n"
            f"Severity: {alert.severity}\n"
            f"Event: {alert.event}\n"
            f"Error Rate: {alert.error_rate * 100:.1f}%\n"
            f"Baseline: {alert.baseline_mean * 100:.1f}%\n"
            f"Z-Score: {alert.z_score:.2f}\n"
            f"Window: {alert.window_seconds}s ({alert.window_total} events, {alert.window_errors} errors)\n"
        )
        if alert.top_errors:
            body += "\nTop Errors:\n"
            for err in alert.top_errors:
                body += f"  - {err.get('message', '?')} × {err.get('count', '?')}\n"

        body += f"\n---\nAlert ID: {alert.id}\n"
        body += json.dumps(alert.model_dump(), indent=2, default=str)

        await asyncio.to_thread(
            client.publish,
            TopicArn=self.topic_arn,
            Subject=subject,
            Message=body,
            MessageAttributes={
                "severity": {"DataType": "String", "StringValue": alert.severity},
                "event": {"DataType": "String", "StringValue": alert.event},
                "alert_key": {"DataType": "String", "StringValue": alert.key},
            },
        )
        logger.info("SNS: published %s alert %s", alert.event, alert.id[:8])
        return "ok"
