"""
Anomaly detector — scores each tick against the baseline and assigns a severity.

The score is z = (rate - center) / scale, where (center, scale) comes from the configured
baseline: median/MAD by default (a robust z-score), EWMA mean/std, or the same-hour
seasonal reference.

Severity classification uses both the z-score (statistical deviation from
the baseline) and an absolute rate floor:
  - NONE: z < Z_LOW or rate < MIN_ABS_RATE
  - LOW:  z ≥ Z_LOW (3.0 by default)
  - MEDIUM: z ≥ Z_MEDIUM (4.5)
  - HIGH: z ≥ Z_HIGH (6.5)
  - CRITICAL: z ≥ Z_CRITICAL (9.0) OR rate ≥ ABS_RATE_CRITICAL (50%)

The absolute rate floor (MIN_ABS_RATE) prevents noise at near-zero baselines
from triggering false alerts. The ABS_RATE_CRITICAL override ensures that
a 50%+ error rate is always flagged as critical regardless of statistical history.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from app.baseline import Baseline
from app.config import Settings
from app.models import DetectionResult, Severity


def _iso(now: float | None) -> str:
    dt = datetime.now(timezone.utc) if now is None else datetime.fromtimestamp(now, timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def classify_severity(z: float, rate: float, cfg: Settings) -> Severity:
    """
    Map a z-score and error rate to a severity level.

    Uses both statistical (z-score) and absolute (rate) thresholds.
    The absolute rate critical override ensures catastrophic failure
    is always flagged, even during warm-up or after baseline drift.
    """
    if rate < cfg.min_abs_rate:
        return Severity.NONE

    if rate >= cfg.abs_rate_critical or z >= cfg.z_critical:
        return Severity.CRITICAL
    if z >= cfg.z_high:
        return Severity.HIGH
    if z >= cfg.z_medium:
        return Severity.MEDIUM
    if z >= cfg.z_low:
        return Severity.LOW

    return Severity.NONE


class Detector:
    """
    Stateless anomaly detector — evaluates one tick at a time.

    Given a window snapshot and a baseline, computes the z-score and
    severity. The AlertManager handles lifecycle (confirm/resolve ticks).
    """

    def __init__(self, cfg: Settings):
        self.cfg = cfg

    def evaluate(self, snapshot: dict, baseline: Baseline, now: float | None = None) -> DetectionResult | None:
        """
        Evaluate the current window snapshot against the baseline.

        Returns None if the baseline isn't ready yet.
        Returns a DetectionResult with the z-score, severity, and whether
        the current tick is breaching the threshold.
        """
        if not baseline.ready:
            return None

        rate = snapshot["error_rate"]
        ref = baseline.reference(now)
        mean = ref.center
        # Sampling-noise floor: a rate measured over n events can't be trusted more precisely
        # than the binomial standard error sqrt(p(1-p)/n). The baseline's scale comes from
        # past windows; when traffic drops (night, low-volume services) the current window
        # is noisier than that history, and this keeps small-n noise from looking anomalous.
        n = snapshot["total"]
        noise = math.sqrt(max(mean, 1e-4) * (1 - mean) / n) if n else 0.0
        std = max(ref.scale, noise)

        # z-score: how many standard deviations above the mean
        z = (rate - mean) / std if std > 0 else 0.0

        severity = classify_severity(z, rate, self.cfg)
        breaching = severity > Severity.NONE

        return DetectionResult(
            ts=_iso(now),
            rate=round(rate, 6),
            z=round(z, 4),
            severity=severity,
            breaching=breaching,
            baseline_mean=round(mean, 6),
            baseline_std=round(std, 6),
            window_total=snapshot["total"],
            window_errors=snapshot["errors"],
        )
