"""Tests for the AlertManager — confirm ticks, escalation, resolve, cooldown."""

import pytest
from app.alerts import AlertManager
from app.config import Settings
from app.models import DetectionResult, Severity


@pytest.fixture
def cfg():
    return Settings(
        confirm_ticks=2, resolve_ticks=3, alert_cooldown_sec=120,
        z_low=3.0, z_medium=4.5, z_high=6.5, z_critical=9.0,
        abs_rate_critical=0.50, min_abs_rate=0.05,
    )


def _make_result(severity: Severity, rate: float = 0.10, z: float = 5.0) -> DetectionResult:
    """Helper to create a DetectionResult."""
    return DetectionResult(
        ts="2026-09-28T10:00:00Z",
        rate=rate, z=z, severity=severity, breaching=severity > Severity.NONE,
        baseline_mean=0.02, baseline_std=0.01,
        window_total=100, window_errors=int(rate * 100),
    )


class TestConfirmTicks:
    def test_no_alert_on_single_breach(self, cfg):
        """One breach tick is not enough — need confirm_ticks consecutive."""
        am = AlertManager(cfg)
        result = _make_result(Severity.MEDIUM)
        events = am.process(result)
        assert len(events) == 0

    def test_alert_opened_after_confirm_ticks(self, cfg):
        am = AlertManager(cfg)
        result = _make_result(Severity.MEDIUM)

        events1 = am.process(result)
        assert len(events1) == 0  # First tick

        events2 = am.process(result)
        assert len(events2) == 1  # Second tick → OPENED
        assert events2[0].event == "OPENED"
        assert events2[0].severity == "MEDIUM"

    def test_breach_count_resets_on_calm(self, cfg):
        am = AlertManager(cfg)
        # One breach
        am.process(_make_result(Severity.MEDIUM))
        # One calm tick
        am.process(_make_result(Severity.NONE, rate=0.02, z=0.5))
        # One more breach — should NOT open (reset)
        events = am.process(_make_result(Severity.MEDIUM))
        assert len(events) == 0


class TestEscalation:
    def test_escalation_emits_event(self, cfg):
        am = AlertManager(cfg)

        # Open at MEDIUM
        am.process(_make_result(Severity.MEDIUM))
        am.process(_make_result(Severity.MEDIUM))  # → OPENED

        # Escalate to HIGH
        events = am.process(_make_result(Severity.HIGH, z=7.0))
        assert len(events) == 1
        assert events[0].event == "ESCALATED"
        assert events[0].severity == "HIGH"

    def test_no_event_on_same_severity(self, cfg):
        am = AlertManager(cfg)
        am.process(_make_result(Severity.MEDIUM))
        am.process(_make_result(Severity.MEDIUM))

        # Same severity, no escalation event
        events = am.process(_make_result(Severity.MEDIUM))
        assert len(events) == 0

    def test_no_event_on_downgrade(self, cfg):
        am = AlertManager(cfg)
        am.process(_make_result(Severity.HIGH, z=7.0))
        am.process(_make_result(Severity.HIGH, z=7.0))

        # Downgrade to MEDIUM — no event
        events = am.process(_make_result(Severity.MEDIUM))
        assert len(events) == 0


class TestResolve:
    def test_resolve_after_calm_ticks(self, cfg):
        am = AlertManager(cfg)

        # Open
        am.process(_make_result(Severity.MEDIUM))
        am.process(_make_result(Severity.MEDIUM))

        # 3 calm ticks → RESOLVED
        calm = _make_result(Severity.NONE, rate=0.02, z=0.5)
        events1 = am.process(calm)
        events2 = am.process(calm)
        events3 = am.process(calm)

        assert len(events1) == 0
        assert len(events2) == 0
        assert len(events3) == 1
        assert events3[0].event == "RESOLVED"
        assert events3[0].status == "RESOLVED"

    def test_resolve_resets_on_breach(self, cfg):
        am = AlertManager(cfg)

        # Open
        am.process(_make_result(Severity.MEDIUM))
        am.process(_make_result(Severity.MEDIUM))

        # 2 calm ticks
        calm = _make_result(Severity.NONE, rate=0.02, z=0.5)
        am.process(calm)
        am.process(calm)

        # Breach again — resets calm count
        am.process(_make_result(Severity.MEDIUM))

        # 3 more calm ticks needed
        events = am.process(calm)
        assert len(events) == 0  # Only 1 calm tick after the breach


class TestCooldown:
    def test_no_reopen_during_cooldown(self, cfg):
        """After resolving, can't re-open immediately (flap protection)."""
        am = AlertManager(cfg)

        # Open and resolve
        am.process(_make_result(Severity.MEDIUM))
        am.process(_make_result(Severity.MEDIUM))  # OPENED

        calm = _make_result(Severity.NONE, rate=0.02, z=0.5)
        am.process(calm)
        am.process(calm)
        am.process(calm)  # RESOLVED

        # Try to open again immediately — should be blocked by cooldown
        events = am.process(_make_result(Severity.MEDIUM))
        assert len(events) == 0
        events = am.process(_make_result(Severity.MEDIUM))
        assert len(events) == 0


class TestNoneResult:
    def test_none_result_returns_empty(self, cfg):
        am = AlertManager(cfg)
        events = am.process(None)
        assert events == []
