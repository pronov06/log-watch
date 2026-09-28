"""End-to-end pipeline test — feeding synthetic events and verifying alerts and bus envelopes."""

import asyncio
from datetime import datetime, timezone
import pytest

from app.bus import EventBus
from app.config import Settings
from app.pipeline import Pipeline


@pytest.mark.asyncio
async def test_pipeline_e2e_anomaly_and_recovery(tmp_path):
    log_file = tmp_path / "test_app.log"
    log_file.touch()

    # Small warmup and intervals for fast deterministic test
    cfg = Settings(
        log_file_path=str(log_file),
        baseline_path=str(tmp_path / "baseline.json"),
        tail_poll_interval_sec=0.05,
        window_seconds=2,
        eval_interval_sec=0.2,
        baseline_warmup_samples=3,
        min_events_in_window=5,
        min_abs_rate=0.05,
        confirm_ticks=2,
        resolve_ticks=2,
        alert_cooldown_sec=1,
        publish_mode="dry_run",
    )
    bus = EventBus(ring_size=100)
    pipeline = Pipeline(cfg, bus)

    # Subscribe to bus events
    queue = bus.subscribe()

    await pipeline.start()
    try:
        # 1. Warm-up phase: generate normal traffic (~2% error)
        start_time = asyncio.get_event_loop().time()
        while not pipeline.baseline.ready and (asyncio.get_event_loop().time() - start_time) < 4.0:
            with open(log_file, "a") as f:
                f.write('2026-09-28T10:00:00.000Z ERROR service=test msg="test error"\n')
                for _ in range(19):
                    f.write('2026-09-28T10:00:00.000Z INFO service=test msg="ok"\n')
            await asyncio.sleep(0.2)

        # Baseline should be ready
        assert pipeline.baseline.ready

        # 2. Inject spike (18 errors, 2 info = 90% error)
        opened = False
        start_time = asyncio.get_event_loop().time()
        while not opened and (asyncio.get_event_loop().time() - start_time) < 4.0:
            with open(log_file, "a") as f:
                for _ in range(18):
                    f.write('2026-09-28T10:00:00.000Z ERROR service=test msg="database connection failed"\n')
                for _ in range(2):
                    f.write('2026-09-28T10:00:00.000Z INFO service=test msg="ok"\n')
            await asyncio.sleep(0.2)

            while not queue.empty():
                envelope = queue.get_nowait()
                if envelope.type == "alert" and envelope.data.get("event") == "OPENED":
                    opened = True
                    assert envelope.data.get("severity") in ["HIGH", "CRITICAL", "MEDIUM"]

        assert opened, "Expected OPENED alert during spike"

        # 3. Recovery phase: clean traffic (wait > window_seconds=2 so spike ages out)
        resolved = False
        start_time = asyncio.get_event_loop().time()
        while not resolved and (asyncio.get_event_loop().time() - start_time) < 6.0:
            with open(log_file, "a") as f:
                for _ in range(10):
                    f.write('2026-09-28T10:00:00.000Z INFO service=test msg="all clear"\n')
            await asyncio.sleep(0.3)

            while not queue.empty():
                envelope = queue.get_nowait()
                if envelope.type == "alert" and envelope.data.get("event") == "RESOLVED":
                    resolved = True

        assert resolved, "Expected RESOLVED alert after recovery"
        # Warm-up traffic was 5% errors; the 90% spike must not have poisoned the baseline.
        assert pipeline.baseline.mean < 0.10, pipeline.baseline.mean

    finally:
        bus.unsubscribe(queue)
        await pipeline.stop()


def test_invalid_config_exits_with_readable_message(monkeypatch):
    from app.config import get_settings
    monkeypatch.setenv("BASELINE_ALPHA", "2")
    with pytest.raises(SystemExit) as exc:
        get_settings()
    assert "BASELINE_ALPHA" in str(exc.value)

    monkeypatch.delenv("BASELINE_ALPHA")
    monkeypatch.setenv("Z_LOW", "20")
    with pytest.raises(SystemExit) as exc:
        get_settings()
    assert "Z thresholds must increase" in str(exc.value)


def test_json_log_formatter_emits_fields():
    import json
    import logging
    from app.logging_setup import JsonFormatter
    rec = logging.makeLogRecord({"name": "t", "levelname": "INFO", "msg": "hi %s", "args": ("x",), "alert_id": "a1"})
    out = json.loads(JsonFormatter().format(rec))
    assert out["msg"] == "hi x" and out["alert_id"] == "a1" and out["ts"].endswith("Z")


@pytest.mark.parametrize("freeze,open_alert,breaching,reliable,expected", [
    (True, False, False, True, True),    # calm, reliable → learn
    (True, False, True, True, False),    # breaching samples never teach the baseline
    (True, False, False, False, False),  # too few events in window
    (True, True, False, True, False),    # frozen while an alert is open
    (False, True, False, True, True),    # freeze disabled → calm ticks still learn
])
def test_baseline_update_policy(tmp_path, freeze, open_alert, breaching, reliable, expected):
    cfg = Settings(freeze_baseline_during_alert=freeze, seasonal_enabled=False, baseline_path=str(tmp_path / "b.json"))
    pipeline = Pipeline(cfg, EventBus())
    pipeline.baseline.ready = True
    pipeline.alert_manager.has_open_alert = lambda key="error_rate:global": open_alert
    assert pipeline.evaluator.should_update_baseline(reliable, breaching) is expected
