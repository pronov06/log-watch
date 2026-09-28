"""
Console publisher — dry-run mode that pretty-prints alerts to stdout.

This is the default publisher when PUBLISH_MODE=dry_run, allowing the
project to run with no AWS account at all.
"""

from __future__ import annotations

import json
import logging

from app.models import Alert

logger = logging.getLogger(__name__)


class ConsolePublisher:
    """Dry-run publisher that logs alerts to stdout in a readable format."""

    async def publish(self, alert: Alert) -> str:
        """Pretty-print the alert to the console."""
        data = alert.model_dump()
        severity = data.get("severity", "UNKNOWN")
        event = data.get("event", "UNKNOWN")
        title = data.get("title", "")

        # Color-coded severity for terminal output
        colors = {
            "LOW": "\033[93m",       # Yellow
            "MEDIUM": "\033[33m",    # Orange
            "HIGH": "\033[91m",      # Red
            "CRITICAL": "\033[91;1m",# Bold red
        }
        reset = "\033[0m"
        color = colors.get(severity, "")

        logger.info(
            "%s[%s] %s: %s%s",
            color, severity, event, title, reset,
        )
        logger.debug("Alert details: %s", json.dumps(data, indent=2, default=str))

        return "ok"
