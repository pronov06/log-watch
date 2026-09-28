"""
REST API endpoints.

Serves:
- /api/health — liveness check with pipeline status
- /api/config — non-secret thresholds for the frontend
- /api/metrics — recent metric points for chart hydration
- /api/alerts — alert history with optional status filter
- /api/alerts/active — currently open alerts
- /api/alerts/{id}/ack — acknowledge an alert
- /api/poll — polling fallback (all envelopes since a given seq)
- /api/logs/recent — last N parsed log lines
- /api/sim/spike — trigger a simulated anomaly (demo only)
- /api/sim/recover — end a simulated anomaly
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


class AckRequest(BaseModel):
    by: str = "anonymous"


class SimSpikeRequest(BaseModel):
    duration_sec: int = 60
    error_ratio: float = 0.35


# ---------------------------------------------------------------------------
# Health & config
# ---------------------------------------------------------------------------

@router.get("/health")
async def health(request: Request):
    """Liveness check with pipeline status."""
    app = request.app
    pipeline = app.state.pipeline
    cfg = app.state.cfg
    bus = app.state.bus

    return {
        "status": "ok",
        "uptime": round(time.time() - app.state.start_time, 1),
        "tailing": pipeline.tailer._running,
        "baseline_ready": pipeline.baseline.ready,
        "baseline_samples": pipeline.baseline.samples,
        "baseline_warmup_target": cfg.baseline_warmup_samples,
        "ws_clients": bus.subscriber_count,
        "publish_mode": cfg.publish_mode,
        "lines_read": pipeline.tailer.lines_read,
        "lines_dropped": pipeline.tailer.lines_dropped,
    }


@router.get("/config")
async def get_config(request: Request):
    """Non-secret thresholds for the frontend (chart reference lines, etc.)."""
    cfg = request.app.state.cfg
    return {
        "window_seconds": cfg.window_seconds,
        "eval_interval_sec": cfg.eval_interval_sec,
        "z_low": cfg.z_low,
        "z_medium": cfg.z_medium,
        "z_high": cfg.z_high,
        "z_critical": cfg.z_critical,
        "abs_rate_critical": cfg.abs_rate_critical,
        "min_abs_rate": cfg.min_abs_rate,
        "confirm_ticks": cfg.confirm_ticks,
        "resolve_ticks": cfg.resolve_ticks,
        "baseline_warmup_samples": cfg.baseline_warmup_samples,
        "sim_enabled": cfg.enable_sim,
    }


# ---------------------------------------------------------------------------
# Metrics & alerts
# ---------------------------------------------------------------------------

@router.get("/metrics")
async def get_metrics(request: Request, minutes: int = 30):
    """Recent metric points for chart hydration on page load."""
    bus = request.app.state.bus
    return bus.get_recent_metrics(minutes=minutes)


@router.get("/alerts")
async def get_alerts(request: Request, status: str | None = None, limit: int = 50):
    """Alert history, newest first, optionally filtered by status."""
    bus = request.app.state.bus
    return bus.get_alerts(status=status, limit=limit)


@router.get("/alerts/active")
async def get_active_alerts(request: Request):
    """Currently OPEN alerts."""
    bus = request.app.state.bus
    return bus.get_active_alerts()


@router.post("/alerts/{alert_id}/ack")
async def ack_alert(alert_id: str, body: AckRequest, request: Request):
    """Acknowledge an alert."""
    # Find the alert in the bus store and mark it
    bus = request.app.state.bus
    for envelope in bus._alert_store:
        if envelope.data.get("id") == alert_id:
            envelope.data["acknowledged"] = True
            envelope.data["acknowledged_by"] = body.by
            return {"status": "ok", "alert_id": alert_id}
    raise HTTPException(status_code=404, detail="Alert not found")


# ---------------------------------------------------------------------------
# Polling fallback
# ---------------------------------------------------------------------------

@router.get("/poll")
async def poll(request: Request, since_seq: int = 0):
    """
    Polling fallback: return all envelopes with seq > since_seq.

    Used by the frontend when WebSocket is unavailable.
    """
    bus = request.app.state.bus
    envelopes, latest = bus.since(since_seq)
    return {
        "envelopes": [e.model_dump() for e in envelopes],
        "latest_seq": latest,
    }


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

@router.get("/logs/recent")
async def get_recent_logs(request: Request, limit: int = 100):
    """Last N parsed log lines for the log tail."""
    bus = request.app.state.bus
    return bus.get_recent_logs(limit=limit)


# ---------------------------------------------------------------------------
# Simulator controls (demo only, guarded by ENABLE_SIM)
# ---------------------------------------------------------------------------

@router.post("/sim/spike")
async def sim_spike(body: SimSpikeRequest, request: Request):
    """Trigger a simulated error spike."""
    cfg = request.app.state.cfg
    if not cfg.enable_sim:
        raise HTTPException(status_code=403, detail="Simulator not enabled")

    control_path = Path("./data/sim_control.json")
    control_path.parent.mkdir(parents=True, exist_ok=True)
    control_path.write_text(json.dumps({
        "action": "spike",
        "error_ratio": body.error_ratio,
        "duration_sec": body.duration_sec,
        "started_at": time.time(),
    }), encoding="utf-8")

    logger.info("Sim spike triggered: ratio=%.2f duration=%ds",
                body.error_ratio, body.duration_sec)
    return {"status": "ok", "action": "spike", "duration_sec": body.duration_sec}


@router.post("/sim/recover")
async def sim_recover(request: Request):
    """End the simulated anomaly."""
    cfg = request.app.state.cfg
    if not cfg.enable_sim:
        raise HTTPException(status_code=403, detail="Simulator not enabled")

    control_path = Path("./data/sim_control.json")
    if control_path.exists():
        control_path.write_text(json.dumps({"action": "recover"}), encoding="utf-8")

    logger.info("Sim recover triggered")
    return {"status": "ok", "action": "recover"}
