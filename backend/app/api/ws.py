"""
WebSocket endpoint for real-time streaming.

On connect:
  - Sends a "snapshot" envelope with recent metrics, active alerts, baseline, and config
  - Then streams: metric (every eval tick), alert (on lifecycle events),
    log (sampled), heartbeat (every 15s)

Features:
  - Per-client bounded queue (maxsize=200) with backpressure
  - Clean disconnect handling
  - Ping/pong support
  - Heartbeat every 15 seconds to keep connections alive
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

HEARTBEAT_INTERVAL = 15  # seconds


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time event streaming.

    Each connected client gets its own bounded queue from the event bus.
    """
    await websocket.accept()

    app = websocket.app
    bus = app.state.bus
    cfg = app.state.cfg
    pipeline = app.state.pipeline

    # Subscribe to the event bus
    client_queue = bus.subscribe(maxsize=200)

    try:
        # Send initial snapshot
        snapshot = {
            "type": "snapshot",
            "seq": bus.latest_seq,
            "ts": "",
            "data": {
                "boot_id": bus.boot_id,
                "metrics": bus.get_recent_metrics(minutes=5),
                "active_alerts": bus.get_active_alerts(),
                "baseline": pipeline.baseline.state(),
                "config": {
                    "window_seconds": cfg.window_seconds,
                    "eval_interval_sec": cfg.eval_interval_sec,
                    "z_low": cfg.z_low,
                    "z_medium": cfg.z_medium,
                    "z_high": cfg.z_high,
                    "z_critical": cfg.z_critical,
                    "abs_rate_critical": cfg.abs_rate_critical,
                    "min_abs_rate": cfg.min_abs_rate,
                    "sim_enabled": cfg.enable_sim,
                },
            },
        }
        await websocket.send_json(snapshot)

        # Run two tasks: send events + receive pings
        send_task = asyncio.create_task(_send_loop(websocket, client_queue))
        recv_task = asyncio.create_task(_recv_loop(websocket))
        heartbeat_task = asyncio.create_task(_heartbeat_loop(websocket))

        # Wait for any to finish (disconnect or error)
        done, pending = await asyncio.wait(
            {send_task, recv_task, heartbeat_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as exc:
        logger.warning("WebSocket error: %s", exc)
    finally:
        bus.unsubscribe(client_queue)


async def _send_loop(websocket: WebSocket, queue: asyncio.Queue) -> None:
    """Send events from the client's queue to the WebSocket."""
    while True:
        try:
            envelope = await queue.get()
            await websocket.send_json(envelope.model_dump())
        except asyncio.CancelledError:
            break
        except Exception:
            break


async def _recv_loop(websocket: WebSocket) -> None:
    """Receive messages from the client (ping/pong support)."""
    while True:
        try:
            data = await websocket.receive_json()
            if isinstance(data, dict) and data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
        except (WebSocketDisconnect, asyncio.CancelledError):
            break
        except Exception:
            break


async def _heartbeat_loop(websocket: WebSocket) -> None:
    """Send heartbeat messages to keep the connection alive."""
    while True:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            await websocket.send_json({
                "type": "heartbeat",
                "seq": 0,
                "ts": "",
                "data": {},
            })
        except (asyncio.CancelledError, Exception):
            break
