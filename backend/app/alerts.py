"""
Alert Manager — lifecycle, deduplication, flap protection.

State machine per alert_key (e.g. "error_rate:global"):

    IDLE → (confirm_ticks breaches) → OPEN → (severity ↑) → ESCALATED
      ↑                                 │
      └── RESOLVED ← (resolve_ticks calm + cooldown before re-open)

Events emitted:
  - OPENED: first confirmed breach
  - ESCALATED: severity goes UP (no event for downgrade, but live alert's
    current_severity is updated)
  - RESOLVED: calm for resolve_ticks consecutive ticks (includes duration
    and peak severity)

Never emits repeated events while severity is unchanged — keeps CloudWatch
and SNS streams clean.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from app.config import Settings
from app.models import Alert, DetectionResult, Severity

logger = logging.getLogger(__name__)


class _AlertState:
    """Internal state for a single alert key."""

    def __init__(self):
        self.status: str = "IDLE"  # IDLE | PENDING | OPEN | COOLDOWN
        self.alert: Alert | None = None
        self.breach_count: int = 0
        self.calm_count: int = 0
        self.current_severity: Severity = Severity.NONE
        self.peak_severity: Severity = Severity.NONE
        self.resolved_at: float = 0.0  # timestamp for cooldown


class AlertManager:
    """
    Manages alert lifecycle with hysteresis (confirm/resolve ticks + cooldown).

    Call process() on each evaluation tick with the DetectionResult.
    Returns a list of Alert events to emit (0, 1, or rarely 2).
    """

    def __init__(self, cfg: Settings, window_seconds: int = 60):
        self.cfg = cfg
        self.window_seconds = window_seconds
        self._states: dict[str, _AlertState] = {}

    def _get_state(self, key: str) -> _AlertState:
        if key not in self._states:
            self._states[key] = _AlertState()
        return self._states[key]

    def has_open_alert(self, key: str = "error_rate:global") -> bool:
        """Check if there's a currently open alert for the given key."""
        state = self._states.get(key)
        return state is not None and state.status == "OPEN"

    def process(
        self,
        result: DetectionResult | None,
        key: str = "error_rate:global",
        top_errors: list[dict] | None = None,
    ) -> list[Alert]:
        """
        Process one evaluation tick and return any alert events to emit.

        Returns an empty list most of the time. Returns one Alert on
        OPENED, ESCALATED, or RESOLVED transitions.
        """
        if result is None:
            return []

        state = self._get_state(key)
        events: list[Alert] = []
        now = time.time()
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        breaching = result.breaching

        if state.status == "IDLE" or state.status == "COOLDOWN":
            if breaching:
                # Check cooldown
                if state.status == "COOLDOWN":
                    if (now - state.resolved_at) < self.cfg.alert_cooldown_sec:
                        return []  # Still in cooldown, ignore
                    # Cooldown expired, transition back to IDLE logic
                    state.status = "IDLE"

                state.breach_count += 1
                state.calm_count = 0

                if state.breach_count >= self.cfg.confirm_ticks:
                    # Confirmed breach → OPEN
                    state.status = "OPEN"
                    state.current_severity = result.severity
                    state.peak_severity = result.severity

                    alert = Alert(
                        id=str(uuid4()),
                        key=key,
                        status="OPEN",
                        event="OPENED",
                        severity=result.severity.name,
                        peak_severity=result.severity.name,
                        title=self._make_title(result),
                        error_rate=result.rate,
                        baseline_mean=result.baseline_mean,
                        baseline_std=result.baseline_std,
                        z_score=result.z,
                        window_seconds=self.window_seconds,
                        window_total=result.window_total,
                        window_errors=result.window_errors,
                        top_errors=top_errors or [],
                        opened_at=now_iso,
                        updated_at=now_iso,
                    )
                    state.alert = alert
                    events.append(alert)
                    logger.info("Alert OPENED: %s [%s] z=%.2f rate=%.4f",
                                key, result.severity.name, result.z, result.rate)
            else:
                state.breach_count = 0

        elif state.status == "OPEN":
            if breaching:
                state.calm_count = 0

                # Check for escalation (severity went UP)
                if result.severity > state.current_severity:
                    state.current_severity = result.severity
                    state.peak_severity = max(state.peak_severity, result.severity)

                    alert = Alert(
                        id=state.alert.id if state.alert else str(uuid4()),
                        key=key,
                        status="OPEN",
                        event="ESCALATED",
                        severity=result.severity.name,
                        peak_severity=state.peak_severity.name,
                        title=self._make_title(result),
                        error_rate=result.rate,
                        baseline_mean=result.baseline_mean,
                        baseline_std=result.baseline_std,
                        z_score=result.z,
                        window_seconds=self.window_seconds,
                        window_total=result.window_total,
                        window_errors=result.window_errors,
                        top_errors=top_errors or [],
                        opened_at=state.alert.opened_at if state.alert else now_iso,
                        updated_at=now_iso,
                        detection_latency_sec=state.alert.detection_latency_sec if state.alert else None,
                    )
                    state.alert = alert
                    events.append(alert)
                    logger.info("Alert ESCALATED: %s → %s", key, result.severity.name)
                else:
                    # Update the live alert's stats without emitting an event
                    if state.alert:
                        state.alert.error_rate = result.rate
                        state.alert.z_score = result.z
                        state.alert.updated_at = now_iso
                        state.alert.window_total = result.window_total
                        state.alert.window_errors = result.window_errors
                        if top_errors:
                            state.alert.top_errors = top_errors
            else:
                # Calm tick — check if we should resolve
                state.calm_count += 1

                if state.calm_count >= self.cfg.resolve_ticks:
                    # RESOLVED
                    alert = Alert(
                        id=state.alert.id if state.alert else str(uuid4()),
                        key=key,
                        status="RESOLVED",
                        event="RESOLVED",
                        severity=state.current_severity.name,
                        peak_severity=state.peak_severity.name,
                        title=f"Resolved: {self._make_title(result)}",
                        error_rate=result.rate,
                        baseline_mean=result.baseline_mean,
                        baseline_std=result.baseline_std,
                        z_score=result.z,
                        window_seconds=self.window_seconds,
                        window_total=result.window_total,
                        window_errors=result.window_errors,
                        top_errors=top_errors or [],
                        opened_at=state.alert.opened_at if state.alert else now_iso,
                        updated_at=now_iso,
                        resolved_at=now_iso,
                        detection_latency_sec=state.alert.detection_latency_sec if state.alert else None,
                    )
                    events.append(alert)
                    logger.info("Alert RESOLVED: %s (peak: %s)",
                                key, state.peak_severity.name)

                    # Reset state with cooldown
                    state.status = "COOLDOWN"
                    state.resolved_at = now
                    state.breach_count = 0
                    state.calm_count = 0
                    state.current_severity = Severity.NONE
                    state.peak_severity = Severity.NONE
                    state.alert = None

        return events

    def get_active_alerts(self) -> list[Alert]:
        """Return all currently open alerts."""
        return [
            s.alert for s in self._states.values()
            if s.status == "OPEN" and s.alert is not None
        ]

    @staticmethod
    def _make_title(result: DetectionResult) -> str:
        """Generate a human-readable alert title."""
        rate_pct = f"{result.rate * 100:.1f}%"
        baseline_pct = f"{result.baseline_mean * 100:.1f}%"
        return f"Error rate spike: {rate_pct} (baseline {baseline_pct})"
