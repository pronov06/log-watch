"""Dual-window detection: a fast window catches big spikes quickly, only at >= FAST_MIN_SEVERITY."""

from app.alerts import AlertManager
from app.baseline import make_baseline
from app.config import Settings
from app.detector import Detector
from app.evaluator import Evaluator
from app.window import SlidingWindow


def _snap(rate: float, total: int, seconds: int) -> dict:
    errors = round(rate * total)
    return {"total": total, "errors": errors, "warnings": 0,
            "error_rate": errors / total, "events_per_sec": total / seconds}


def _evaluator(tmp_path, **overrides):
    cfg = Settings(_env_file=None, baseline_path=str(tmp_path / "b.json"), seasonal_enabled=False,
                   window_seconds=300, fast_window_seconds=60, eval_interval_sec=5, confirm_ticks=2,
                   baseline_warmup_samples=5, **overrides)
    fast = make_baseline(cfg, ".fast") if cfg.fast_window_seconds else None
    ev = Evaluator(cfg, SlidingWindow(cfg.window_seconds), make_baseline(cfg), Detector(cfg),
                   AlertManager(cfg, cfg.window_seconds), fast_baseline=fast)
    t = 1_000.0
    for i in range(10):  # warm both baselines on calm 2% traffic
        ev.step(t + i * 5, _snap(0.02, 9000, 300), _snap(0.02, 1800, 60))
    return ev, t + 50


def test_fast_window_opens_alert_on_severe_spike_before_main_window(tmp_path):
    ev, t = _evaluator(tmp_path)
    opened = []
    for i in range(2):  # 60 s window already at 20% errors; 5 min window still only 5.6%/4%
        tick = ev.step(t + i * 5, _snap(0.04, 9000, 300), _snap(0.20, 1800, 60))
        opened += [a for a in tick.alerts if a.event == "OPENED"]
    assert len(opened) == 1
    assert opened[0].window_seconds == 60 and opened[0].severity in ("HIGH", "CRITICAL")
    assert "over 60s" in opened[0].title
    assert tick.metric["triggered_by"] == "60s"


def test_fast_window_ignores_moderate_blips(tmp_path):
    """A short blip lifts the 60 s rate to ~6% (MEDIUM at most): below FAST_MIN_SEVERITY=HIGH."""
    ev, t = _evaluator(tmp_path)
    for i in range(6):
        tick = ev.step(t + i * 5, _snap(0.025, 9000, 300), _snap(0.063, 1800, 60))
        assert tick.alerts == []
    assert tick.metric["fast_error_rate"] > 0.06 and tick.metric["severity"] == "NONE"


def test_main_window_still_alerts_at_any_severity(tmp_path):
    ev, t = _evaluator(tmp_path)
    opened = []
    for i in range(2):
        tick = ev.step(t + i * 5, _snap(0.06, 9000, 300), _snap(0.06, 1800, 60))
        opened += [a for a in tick.alerts if a.event == "OPENED"]
    assert len(opened) == 1 and opened[0].window_seconds == 300


def test_fast_window_not_shorter_than_main_is_disabled(tmp_path):
    cfg = Settings(_env_file=None, window_seconds=60, fast_window_seconds=60)
    assert cfg.fast_window_seconds == 0  # older .env with WINDOW_SECONDS=60 keeps working
    assert Settings(_env_file=None, window_seconds=300, fast_window_seconds=0).fast_window_seconds == 0
