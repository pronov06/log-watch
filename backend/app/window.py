"""
Time-bucketed sliding window for computing rolling error rates.

Uses 1-second buckets in a deque. Memory = O(window_seconds), cost per event = O(1).
The window evicts stale buckets on each snapshot() call.

Design note: we use processing time (not the log event's own timestamp) for bucketing.
This is simpler, avoids clock-skew issues, and is sufficient because the evaluator
polls at fixed intervals — so the rate reflects "errors seen in the last N seconds".
"""

from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass, field


@dataclass
class Bucket:
    """A single 1-second time bucket."""
    sec: int
    total: int = 0
    errors: int = 0
    warnings: int = 0
    error_messages: list[str] = field(default_factory=list)


class SlidingWindow:
    """
    Rolling window of log events bucketed by second.

    Call `add()` for every parsed log event.
    Call `snapshot()` to get the current error rate and volume stats.
    """

    def __init__(self, window_seconds: int = 60):
        self.window = window_seconds
        self.buckets: deque[Bucket] = deque()
        self._error_counter: Counter = Counter()

    def add(self, level: str, message: str = "", now: float | None = None) -> None:
        """Record one log event in the appropriate bucket."""
        sec = int(now or time.time())

        # Create a new bucket if needed
        if not self.buckets or self.buckets[-1].sec != sec:
            self.buckets.append(Bucket(sec))

        b = self.buckets[-1]
        b.total += 1

        if level == "ERROR":
            b.errors += 1
            if message:
                b.error_messages.append(message)
                self._error_counter[message] += 1
        elif level == "WARNING":
            b.warnings += 1

    def _evict(self, now: int) -> None:
        """Remove buckets older than the window."""
        cutoff = now - self.window
        while self.buckets and self.buckets[0].sec <= cutoff:
            old = self.buckets.popleft()
            # Decrement the error message counter for evicted buckets
            for msg in old.error_messages:
                self._error_counter[msg] -= 1
                if self._error_counter[msg] <= 0:
                    del self._error_counter[msg]

    def snapshot(self, now: float | None = None) -> dict:
        """
        Return current window statistics.

        Returns a dict with: total, errors, warnings, error_rate, events_per_sec
        """
        now_i = int(now or time.time())
        self._evict(now_i)

        total = sum(b.total for b in self.buckets)
        errors = sum(b.errors for b in self.buckets)
        warnings = sum(b.warnings for b in self.buckets)

        return {
            "total": total,
            "errors": errors,
            "warnings": warnings,
            "error_rate": (errors / total) if total else 0.0,
            "events_per_sec": total / self.window if self.window else 0.0,
        }

    def top_errors(self, n: int = 3) -> list[dict]:
        """
        Return the top N most frequent error messages currently in the window.

        Used by the AlertManager to attach the "why" to each alert.
        """
        return [
            {"message": msg, "count": count}
            for msg, count in self._error_counter.most_common(n)
            if count > 0
        ]

    def clear(self) -> None:
        """Reset the window (used in tests)."""
        self.buckets.clear()
        self._error_counter.clear()
