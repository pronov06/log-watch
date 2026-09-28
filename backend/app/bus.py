"""
In-memory pub/sub event bus with a ring buffer and monotonic sequence numbers.

Every message gets a `seq` (monotonically increasing integer) which powers:
- Polling fallback: GET /api/poll?since_seq=N
- Client gap detection over WebSocket

Alerts are stored in a separate, longer-lived list so they aren't evicted
by high-volume metric messages.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone

from app.models import Envelope

logger = logging.getLogger(__name__)


class EventBus:
    """
    Central event bus for the anomaly detector.

    - publish() assigns a seq, stores in the ring buffer, and pushes to all subscribers
    - subscribe()/unsubscribe() manage async queues for WebSocket clients
    - since(seq) returns buffered items after a given seq (for polling)
    """

    def __init__(self, ring_size: int = 2000):
        self._seq: int = 0
        self._ring: deque[Envelope] = deque(maxlen=ring_size)
        self._alert_store: list[Envelope] = []
        self._subscribers: set[asyncio.Queue] = set()

    @property
    def latest_seq(self) -> int:
        return self._seq

    def publish(self, msg_type: str, data: dict) -> Envelope:
        """
        Publish an event to all subscribers and the ring buffer.

        Returns the envelope with the assigned seq.
        """
        self._seq += 1
        envelope = Envelope(
            type=msg_type,
            seq=self._seq,
            ts=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            data=data,
        )

        self._ring.append(envelope)

        # Keep alerts in a separate long-lived store
        if msg_type == "alert":
            self._alert_store.append(envelope)

        # Fan-out to all connected WebSocket clients
        for q in list(self._subscribers):
            try:
                q.put_nowait(envelope)
            except asyncio.QueueFull:
                # Backpressure: drop oldest non-alert message from the queue
                self._drop_oldest_non_alert(q)
                try:
                    q.put_nowait(envelope)
                except asyncio.QueueFull:
                    logger.warning("Client queue still full after drop, skipping")

        return envelope

    def _drop_oldest_non_alert(self, q: asyncio.Queue) -> None:
        """Drop the oldest non-alert message from a client queue to make room."""
        items = []
        dropped = False
        while not q.empty():
            try:
                item = q.get_nowait()
                if not dropped and item.type != "alert":
                    dropped = True  # Drop this one
                    continue
                items.append(item)
            except asyncio.QueueEmpty:
                break

        # Put remaining items back
        for item in items:
            try:
                q.put_nowait(item)
            except asyncio.QueueFull:
                break

    def since(self, seq: int, max_items: int = 500) -> tuple[list[Envelope], int]:
        """
        Return all envelopes with seq > the given seq, up to max_items.

        Returns (envelopes, latest_seq).
        Used by the polling fallback endpoint.
        """
        result = [e for e in self._ring if e.seq > seq]
        if len(result) > max_items:
            result = result[-max_items:]
        return result, self._seq

    def subscribe(self, maxsize: int = 200) -> asyncio.Queue:
        """Create a new subscriber queue (for a WebSocket client)."""
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers.add(q)
        logger.info("Subscriber added (total: %d)", len(self._subscribers))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove a subscriber queue."""
        self._subscribers.discard(q)
        logger.info("Subscriber removed (total: %d)", len(self._subscribers))

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def get_recent_metrics(self, minutes: int = 5) -> list[dict]:
        """Return recent metric envelopes from the ring buffer."""
        result = [e.data for e in self._ring if e.type == "metric"]
        # Estimate: at 1 metric per eval_interval (5s), 5 min = 60 points
        max_points = minutes * 12  # 12 per minute at 5s interval
        return result[-max_points:]

    def get_alerts(self, status: str | None = None, limit: int = 50) -> list[dict]:
        """Return alerts from the alert store, optionally filtered by status."""
        alerts = [e.data for e in reversed(self._alert_store)]
        if status:
            alerts = [a for a in alerts if a.get("status") == status]
        return alerts[:limit]

    def get_active_alerts(self) -> list[dict]:
        """Return currently OPEN alerts (deduplicated by key, latest event wins)."""
        # Track latest event per alert key
        by_key: dict[str, dict] = {}
        for e in self._alert_store:
            key = e.data.get("key", "")
            by_key[key] = e.data

        return [a for a in by_key.values() if a.get("status") == "OPEN"]

    def get_recent_logs(self, limit: int = 100) -> list[dict]:
        """Return recent log envelopes from the ring buffer."""
        result = [e.data for e in self._ring if e.type == "log"]
        return result[-limit:]
