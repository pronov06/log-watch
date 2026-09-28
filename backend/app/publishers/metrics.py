"""
CloudWatch custom metrics reporter — ErrorRate, ZScore, EventsPerSec, OpenAlerts.

Metric points arrive every eval tick (5 s). Sending each one would be ~17k
PutMetricData calls/day, so points are buffered and flushed as Values/Counts
arrays every `interval_sec`. That keeps full resolution for CloudWatch
statistics at a fraction of the request cost. A CloudWatch alarm on ErrorRate
(see infra/cloudformation.yaml) then works independently of this app's UI.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Callable

from app.publishers.aws import make_client

logger = logging.getLogger(__name__)

NAMESPACE = "LogAnomaly"
MAX_VALUES_PER_DATUM = 150  # PutMetricData limit per MetricDatum


def _to_datum(name: str, values: list[float], unit: str, ts: datetime, dims: list[dict]) -> dict:
    counts = Counter(round(v, 6) for v in values)
    top = counts.most_common(MAX_VALUES_PER_DATUM)
    return {
        "MetricName": name,
        "Dimensions": dims,
        "Timestamp": ts,
        "Values": [v for v, _ in top],
        "Counts": [float(c) for _, c in top],
        "Unit": unit,
    }


class MetricsReporter:
    """Buffers metric points and flushes them to CloudWatch periodically."""

    def __init__(
        self,
        region: str,
        endpoint_url: str = "",
        interval_sec: float = 60.0,
        open_alerts: Callable[[], int] = lambda: 0,
        dimension: str = "global",
    ):
        self.region = region
        self.endpoint_url = endpoint_url or None
        self.interval_sec = interval_sec
        self.open_alerts = open_alerts
        self.dims = [{"Name": "Scope", "Value": dimension}]
        self._buffer: list[dict] = []
        self._client = None
        self._running = False
        self.flushes = 0
        self.failures = 0
        self.last_error: str | None = None

    def add(self, point: dict) -> None:
        """Called synchronously by the pipeline for every metric point."""
        self._buffer.append(point)

    def _get_client(self):
        if self._client is None:
            self._client = make_client("cloudwatch", self.region, self.endpoint_url)
        return self._client

    def build_metric_data(self, points: list[dict]) -> list[dict]:
        ts = datetime.now(timezone.utc)
        rates = [p["error_rate"] for p in points if p.get("error_rate") is not None]
        zs = [p["z"] for p in points if p.get("z") is not None]
        eps = [p["events_per_sec"] for p in points if p.get("events_per_sec") is not None]
        data = []
        if rates:
            data.append(_to_datum("ErrorRate", rates, "None", ts, self.dims))
        if zs:
            data.append(_to_datum("ZScore", zs, "None", ts, self.dims))
        if eps:
            data.append(_to_datum("EventsPerSec", eps, "Count/Second", ts, self.dims))
        data.append(_to_datum("OpenAlerts", [float(self.open_alerts())], "Count", ts, self.dims))
        return data

    async def flush(self) -> None:
        points, self._buffer = self._buffer, []
        if not points:
            return
        data = self.build_metric_data(points)
        try:
            await asyncio.to_thread(
                self._get_client().put_metric_data, Namespace=NAMESPACE, MetricData=data,
            )
            self.flushes += 1
            self.last_error = None
        except Exception as exc:  # never fatal: metrics are best-effort
            self.failures += 1
            self.last_error = str(exc)[:200]
            logger.warning("CloudWatch metrics flush failed (%d points dropped): %s", len(points), exc)

    async def run(self) -> None:
        self._running = True
        while self._running:
            await asyncio.sleep(self.interval_sec)
            await self.flush()

    def stop(self) -> None:
        self._running = False

    def stats(self) -> dict:
        return {"flushes": self.flushes, "failures": self.failures, "last_error": self.last_error}
