"""
Publisher protocol — the interface that all alert publishers must implement.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.models import Alert


@runtime_checkable
class Publisher(Protocol):
    """
    Interface for alert publishers.

    Each publisher receives an Alert and pushes it to an external system
    (CloudWatch, SNS, console, etc.).  Implementations MUST NOT raise —
    they should log errors and return gracefully.
    """

    async def publish(self, alert: Alert) -> str:
        """
        Publish an alert.

        Returns a status string: "ok", "failed", or "skipped".
        """
        ...
