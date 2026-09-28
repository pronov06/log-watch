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

    finally:
        bus.unsubscribe(queue)
        await pipeline.stop()
