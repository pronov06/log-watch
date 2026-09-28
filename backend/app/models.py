"""
Pydantic models shared across the entire backend.

These are the canonical data shapes – the frontend TypeScript types must mirror them exactly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import IntEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------

class Severity(IntEnum):
    """Anomaly severity levels.  The integer value enables >, < comparisons."""
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


# ---------------------------------------------------------------------------
# Log event (output of the parser)
# ---------------------------------------------------------------------------

class LogEvent(BaseModel):
    """A single parsed log line."""
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    level: str = "INFO"
    service: str = "unknown"
    message: str = ""
    raw: str = ""


# ---------------------------------------------------------------------------
# Metric point (output of each evaluation tick)
# ---------------------------------------------------------------------------

class MetricPoint(BaseModel):
    """Snapshot of the sliding window + baseline state at one eval tick."""
    ts: str  # ISO-8601 with Z
    error_rate: float
    total: int
    errors: int
    events_per_sec: float
    baseline_mean: float | None = None
    baseline_std: float | None = None
    upper_band: float | None = None
    lower_band: float | None = None
    z: float | None = None
    severity: str = "NONE"
    ingest_lag_ms_p95: float | None = None


# ---------------------------------------------------------------------------
# Detection result (internal, per-tick output of the detector)
# ---------------------------------------------------------------------------

class DetectionResult(BaseModel):
    """What the detector computed on a single tick."""
    ts: str
    rate: float
    z: float
    severity: Severity
    breaching: bool
    baseline_mean: float
    baseline_std: float
    window_total: int
    window_errors: int


# ---------------------------------------------------------------------------
# Alert (lifecycle-managed by the AlertManager)
# ---------------------------------------------------------------------------

class Alert(BaseModel):
    """An alert with full lifecycle metadata."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    key: str = "error_rate:global"
    status: Literal["OPEN", "RESOLVED"] = "OPEN"
    event: Literal["OPENED", "ESCALATED", "RESOLVED"] = "OPENED"
    severity: str = "LOW"
    peak_severity: str = "LOW"
    title: str = ""
    error_rate: float = 0.0
    baseline_mean: float = 0.0
    baseline_std: float = 0.0
    z_score: float = 0.0
    window_seconds: int = 60
    window_total: int = 0
    window_errors: int = 0
    top_errors: list[dict] = Field(default_factory=list)
    opened_at: str = ""
    updated_at: str = ""
    resolved_at: str | None = None
    detection_latency_sec: float | None = None  # first breaching tick → OPENED
    acknowledged: bool = False
    acknowledged_by: str | None = None
    publish_status: dict = Field(default_factory=dict)  # {"cloudwatch": "ok", "sns": "skipped"}


# ---------------------------------------------------------------------------
# Envelope (the universal message wrapper for WS / bus / polling)
# ---------------------------------------------------------------------------

class Envelope(BaseModel):
    """
    Every message on the event bus and over the WebSocket uses this wrapper.
    `seq` is a monotonically increasing integer used by polling (`?since_seq=`)
    and by clients to detect gaps.
    """
    type: Literal["metric", "alert", "alert_update", "baseline", "log", "snapshot", "heartbeat", "config"] = "metric"
    seq: int = 0
    ts: str = ""
    data: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Baseline state (exposed via the API and WebSocket)
# ---------------------------------------------------------------------------

class BaselineState(BaseModel):
    """Current state of the EWMA baseline, sent to the frontend for rendering."""
    mean: float = 0.0
    std: float = 0.0
    samples: int = 0
    ready: bool = False
    warmup_needed: int = 0
    warmup_pct: float = 0.0
    upper_band: float = 0.0  # mean + z_low * std
    lower_band: float = 0.0  # max(0, mean - z_low * std)
