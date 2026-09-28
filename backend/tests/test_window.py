"""Tests for the sliding window — bucket eviction, rate math, edge cases."""

import pytest
from app.window import SlidingWindow


class TestSlidingWindow:
    def test_empty_window(self):
        w = SlidingWindow(window_seconds=60)
        snap = w.snapshot(now=1000.0)
        assert snap["total"] == 0
        assert snap["errors"] == 0
        assert snap["error_rate"] == 0.0

    def test_single_event(self):
        w = SlidingWindow(window_seconds=60)
        w.add("INFO", now=1000.0)
        snap = w.snapshot(now=1000.0)
        assert snap["total"] == 1
        assert snap["errors"] == 0
        assert snap["error_rate"] == 0.0

    def test_error_rate_math(self):
        w = SlidingWindow(window_seconds=60)
        # Add 80 INFO and 20 ERROR events
        for _ in range(80):
            w.add("INFO", now=1000.0)
        for _ in range(20):
            w.add("ERROR", message="test error", now=1000.0)

        snap = w.snapshot(now=1000.0)
        assert snap["total"] == 100
        assert snap["errors"] == 20
        assert abs(snap["error_rate"] - 0.20) < 0.001

    def test_bucket_eviction(self):
        w = SlidingWindow(window_seconds=10)

        # Add events at second 100
        for _ in range(10):
            w.add("INFO", now=100.0)

        # Add events at second 105
        for _ in range(5):
            w.add("ERROR", message="err", now=105.0)

        # At second 111, the sec=100 bucket should be evicted (cutoff = 111-10 = 101)
        snap = w.snapshot(now=111.0)
        assert snap["total"] == 5
        assert snap["errors"] == 5
        assert snap["error_rate"] == 1.0

    def test_multiple_buckets(self):
        w = SlidingWindow(window_seconds=60)

        w.add("INFO", now=100.0)
        w.add("ERROR", message="err", now=101.0)
        w.add("INFO", now=102.0)

        snap = w.snapshot(now=102.0)
        assert snap["total"] == 3
        assert snap["errors"] == 1

    def test_events_per_sec(self):
        w = SlidingWindow(window_seconds=60)
        for _ in range(120):
            w.add("INFO", now=1000.0)

        snap = w.snapshot(now=1000.0)
        assert snap["events_per_sec"] == 120 / 60  # 2.0

    def test_warnings_tracked(self):
        w = SlidingWindow(window_seconds=60)
        w.add("WARNING", now=1000.0)
        w.add("WARNING", now=1000.0)
        w.add("INFO", now=1000.0)

        snap = w.snapshot(now=1000.0)
        assert snap["warnings"] == 2

    def test_top_errors(self):
        w = SlidingWindow(window_seconds=60)
        for _ in range(10):
            w.add("ERROR", message="timeout", now=1000.0)
        for _ in range(5):
            w.add("ERROR", message="connection refused", now=1000.0)
        for _ in range(3):
            w.add("ERROR", message="auth failed", now=1000.0)

        top = w.top_errors(n=2)
        assert len(top) == 2
        assert top[0]["message"] == "timeout"
        assert top[0]["count"] == 10
        assert top[1]["message"] == "connection refused"
        assert top[1]["count"] == 5

    def test_top_errors_evicted(self):
        w = SlidingWindow(window_seconds=10)
        for _ in range(5):
            w.add("ERROR", message="old error", now=100.0)

        # Evict the old errors
        snap = w.snapshot(now=112.0)
        top = w.top_errors(n=3)
        assert len(top) == 0

    def test_clear(self):
        w = SlidingWindow(window_seconds=60)
        w.add("ERROR", message="err", now=1000.0)
        w.clear()
        snap = w.snapshot(now=1000.0)
        assert snap["total"] == 0
