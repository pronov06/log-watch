"""
CloudWatch Logs publisher — pushes structured alert JSON to a CloudWatch log stream.

Each alert is a single JSON message, queryable with CloudWatch Logs Insights:
  fields @timestamp, severity, title, error_rate
  | filter severity in ["HIGH","CRITICAL"]
  | sort @timestamp desc
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from app.models import Alert

logger = logging.getLogger(__name__)


class CloudWatchPublisher:
    """Publishes alerts to AWS CloudWatch Logs."""

    def __init__(self, log_group: str, log_stream: str, region: str, endpoint_url: str = ""):
        self.log_group = log_group
        self.log_stream = log_stream
        self.region = region
        self.endpoint_url = endpoint_url or None
        self._client = None

    def _get_client(self):
        """Lazy-init the boto3 client."""
        if self._client is None:
            import boto3
            kwargs = {"region_name": self.region}
            if self.endpoint_url:
                kwargs["endpoint_url"] = self.endpoint_url
            self._client = boto3.client("logs", **kwargs)

            # Ensure log group and stream exist
            try:
                self._client.create_log_group(logGroupName=self.log_group)
            except self._client.exceptions.ResourceAlreadyExistsException:
                pass
            try:
                self._client.create_log_stream(
                    logGroupName=self.log_group,
                    logStreamName=self.log_stream,
                )
            except self._client.exceptions.ResourceAlreadyExistsException:
                pass

        return self._client

    async def publish(self, alert: Alert) -> str:
        """Push the alert as a structured JSON log event."""
        try:
            client = await asyncio.to_thread(self._get_client)

            message = json.dumps({
                "service": "log-anomaly-detector",
                "event": alert.event,
                "severity": alert.severity,
                "alert_id": alert.id,
                "title": alert.title,
                "error_rate": alert.error_rate,
                "baseline_mean": alert.baseline_mean,
                "z_score": alert.z_score,
                "window_seconds": alert.window_seconds,
                "top_errors": alert.top_errors,
            }, default=str)

            await asyncio.to_thread(
                client.put_log_events,
                logGroupName=self.log_group,
                logStreamName=self.log_stream,
                logEvents=[{
                    "timestamp": int(time.time() * 1000),
                    "message": message,
                }],
            )
            logger.info("CloudWatch: published %s alert %s", alert.event, alert.id[:8])
            return "ok"

        except Exception as exc:
            logger.error("CloudWatch publish failed: %s", exc)
            return "failed"
