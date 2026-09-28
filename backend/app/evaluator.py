"""
Evaluator — one detection tick: window snapshot → baseline → detector → alert lifecycle.

Synchronous and clock-injectable, so the exact same logic runs in the live pipeline
(called every EVAL_INTERVAL_SEC) and in the offline benchmark (replaying days of
synthetic traffic in seconds).

Dual-window detection (FAST_WINDOW_SECONDS > 0)
-----------------------------------------------
The window size trades detection speed for false alarms (docs/detector-benchmark.md):
a 60 s window catches a spike in ~13 s but also alerts on 20 s self-healing blips;
a 5 min window ignores those blips but needs ~35 s for the same spike. Both run here:

- main window (WINDOW_SECONDS, e.g. 5 min): alerts at any severity
- fast window (FAST_WINDOW_SECONDS, e.g. 60 s): alerts only at >= FAST_MIN_SEVERITY

Each window has its own baseline, because a 60 s error rate is naturally noisier than a
5 min one. The tick's result is the most severe qualifying one, so big spikes open an
alert fast, while blips (which never reach HIGH on the fast path) stay quiet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.alerts import AlertManager
from app.config import Settings
from app.detector import Detector
from app.models import Alert, DetectionResult, Severity
from app.window import SlidingWindow


@dataclass
class TickResult:
    metric: dict
    baseline_state: dict
    alerts: list[Alert] = field(default_factory=list)
    result: DetectionResult | None = None


class Evaluator:
    def __init__(self, cfg: Settings, window: SlidingWindow, baseline, detector: Detector,
                 alert_manager: AlertManager, fast_baseline=None):
        self.cfg = cfg
        self.window = window
        self.baseline = baseline
        self.fast_baseline = fast_baseline if cfg.fast_window_seconds else None
        self.fast_min = Severity[cfg.fast_min_severity]
        self.detector = detector
        self.alert_manager = alert_manager
        # Detection latency = first breaching tick → OPENED (the confirm-ticks cost).
        self._breach_started: float | None = None
        self.last_detect_sec: float | None = None

    def should_update_baseline(self, reliable: bool, breaching: bool, baseline=None) -> bool:
        """
        Only calm, statistically reliable samples may teach the baseline what "normal" is.

        Breaching samples never do. With FREEZE_BASELINE_DURING_ALERT (default) the
        baseline also stays frozen until the alert resolves: the calm-looking ticks inside
        an incident (e.g. a dip between two bursts) would otherwise drag the center up and
        make the rest of the incident look normal (baseline poisoning).
        """
        baseline = baseline if baseline is not None else self.baseline
        if not (reliable and baseline.ready) or breaching:
            return False
        if self.cfg.freeze_baseline_during_alert and self.alert_manager.has_open_alert():
            return False
        return True

    def _assess(self, baseline, snap: dict, window_seconds: int, now: float) -> DetectionResult | None:
        """Learn from / score one window. Returns None while unreliable or warming up."""
        rate = snap["error_rate"]
        # Low-traffic gate: 1 error in 3 requests is 33% but means nothing statistically.
        reliable = snap["total"] >= self.cfg.min_events_in_window
        if reliable:
            baseline.observe(rate, now)  # same-hour profile learns every reliable sample
            if not baseline.ready:
                baseline.warmup_add(rate, now)

        result = None
        if reliable and baseline.ready:
            result = self.detector.evaluate(snap, baseline, now)
            result.window_seconds = window_seconds

        # Rolling baselines learn only from calm ticks of their own window
        own_breach = bool(result and result.severity > Severity.NONE)
        if self.should_update_baseline(reliable, own_breach, baseline):
            baseline.update(rate, now)
        return result

    def _combine(self, main: DetectionResult | None, fast: DetectionResult | None) -> DetectionResult | None:
        candidates = []
        if main and main.breaching:
            candidates.append(main)
        if fast and fast.severity >= self.fast_min:
            candidates.append(fast)
        if candidates:
            return max(candidates, key=lambda r: r.severity)
        return main  # calm (or None while warming up); a sub-threshold fast result is ignored

    def step(self, now: float, snap: dict | None = None, fast_snap: dict | None = None) -> TickResult:
        """
        Run one evaluation at time `now`.

        `snap` / `fast_snap` override the window snapshots (used by the benchmark).
        """
        snap = snap if snap is not None else self.window.snapshot(now)
        main = self._assess(self.baseline, snap, self.cfg.window_seconds, now)

        fast = None
        if self.fast_baseline is not None:
            if fast_snap is None:
                fast_snap = self.window.snapshot(now, seconds=self.cfg.fast_window_seconds)
            fast = self._assess(self.fast_baseline, fast_snap, self.cfg.fast_window_seconds, now)

        result = self._combine(main, fast)
        breaching = bool(result and result.breaching)
        if breaching and self._breach_started is None:
            self._breach_started = now
        elif not breaching and not self.alert_manager.has_open_alert():
            self._breach_started = None

        bstate = self.baseline.state(now)
        ready = self.baseline.ready
        metric = {
            "ts": datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z"),
            "error_rate": round(snap["error_rate"], 6),
            "total": snap["total"],
            "errors": snap["errors"],
            "events_per_sec": round(snap["events_per_sec"], 2),
            "baseline_mean": bstate["mean"] if ready else None,
            "baseline_std": bstate["std"] if ready else None,
            "upper_band": bstate["upper_band"] if ready else None,
            "lower_band": bstate["lower_band"] if ready else None,
            "baseline_source": bstate["source"] if ready else None,
            "z": round(main.z, 4) if main else None,
            "severity": result.severity.name if result else "NONE",
            "fast_error_rate": round(fast_snap["error_rate"], 6) if fast_snap is not None else None,
            "fast_z": round(fast.z, 4) if fast else None,
            "triggered_by": (f"{result.window_seconds}s" if breaching else None),
        }

        alerts = self.alert_manager.process(result, top_errors=self.window.top_errors(n=3), now=now)
        for alert in alerts:
            if alert.event == "OPENED" and self._breach_started is not None:
                self.last_detect_sec = round(now - self._breach_started, 2)
                alert.detection_latency_sec = self.last_detect_sec
        return TickResult(metric, bstate, alerts, result)
