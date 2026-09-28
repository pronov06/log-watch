"""Tests for the anomaly detector — severity boundaries, absolute-rate floor, reliability gate."""

import pytest
from app.config import Settings
from app.detector import Detector, classify_severity
from app.baseline import Baseline
from app.models import Severity


@pytest.fixture
def cfg():
    return Settings(
        z_low=3.0, z_medium=4.5, z_high=6.5, z_critical=9.0,
        abs_rate_critical=0.50, min_abs_rate=0.05,
    )


class TestClassifySeverity:
    def test_below_min_rate(self, cfg):
        """Rate below MIN_ABS_RATE should always be NONE, even with high z."""
        assert classify_severity(z=10.0, rate=0.03, cfg=cfg) == Severity.NONE

    def test_none_below_z_low(self, cfg):
        assert classify_severity(z=2.9, rate=0.10, cfg=cfg) == Severity.NONE

    def test_low_at_z_low(self, cfg):
        assert classify_severity(z=3.0, rate=0.10, cfg=cfg) == Severity.LOW

    def test_medium_at_z_medium(self, cfg):
        assert classify_severity(z=4.5, rate=0.10, cfg=cfg) == Severity.MEDIUM

    def test_high_at_z_high(self, cfg):
        assert classify_severity(z=6.5, rate=0.10, cfg=cfg) == Severity.HIGH

    def test_critical_at_z_critical(self, cfg):
        assert classify_severity(z=9.0, rate=0.10, cfg=cfg) == Severity.CRITICAL

    def test_critical_at_abs_rate(self, cfg):
        """Rate >= 50% is always CRITICAL regardless of z."""
        assert classify_severity(z=1.0, rate=0.50, cfg=cfg) == Severity.CRITICAL
        assert classify_severity(z=0.0, rate=0.60, cfg=cfg) == Severity.CRITICAL

    def test_just_below_boundaries(self, cfg):
        assert classify_severity(z=2.99, rate=0.10, cfg=cfg) == Severity.NONE
        assert classify_severity(z=4.49, rate=0.10, cfg=cfg) == Severity.LOW
        assert classify_severity(z=6.49, rate=0.10, cfg=cfg) == Severity.MEDIUM
        assert classify_severity(z=8.99, rate=0.10, cfg=cfg) == Severity.HIGH


class TestDetector:
    def test_returns_none_when_baseline_not_ready(self, cfg):
        d = Detector(cfg)
        baseline = Baseline(warmup_samples=10, alpha=0.05, min_std=0.01)
        snap = {"error_rate": 0.5, "total": 100, "errors": 50, "events_per_sec": 10}
        assert d.evaluate(snap, baseline) is None

    def test_evaluate_normal(self, cfg):
        d = Detector(cfg)
        baseline = Baseline(warmup_samples=2, alpha=0.05, min_std=0.01)
        baseline.warmup_add(0.02)
        baseline.warmup_add(0.02)

        snap = {"error_rate": 0.02, "total": 100, "errors": 2, "events_per_sec": 10}
        result = d.evaluate(snap, baseline)
        assert result is not None
        assert result.severity == Severity.NONE
        assert not result.breaching

    def test_evaluate_spike(self, cfg):
        d = Detector(cfg)
        baseline = Baseline(warmup_samples=2, alpha=0.05, min_std=0.01)
        baseline.warmup_add(0.02)
        baseline.warmup_add(0.02)

        # 30% error rate with 2% baseline and ~1% std → z = (0.30-0.02)/0.01 = 28
        snap = {"error_rate": 0.30, "total": 100, "errors": 30, "events_per_sec": 10}
        result = d.evaluate(snap, baseline)
        assert result is not None
        assert result.severity == Severity.CRITICAL
        assert result.breaching
