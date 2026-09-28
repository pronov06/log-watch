"""
Live end-to-end smoke test: real backend process + real log generator + real WebSocket.

    python scripts/smoke_realtime.py            # exits 0 on success, 1 on failure

What it proves (G4):
  1. backend becomes ready and the baseline warms up on generated traffic
  2. POST /api/sim/spike → an OPENED alert arrives over /ws within the latency budget
     EVAL + CONFIRM_TICKS*EVAL + 1 s, with a severity consistent with its z-score/rate
  3. /api/poll?since_seq= returns the same alert (polling fallback parity)
  4. the dry-run publisher delivered it (alert_update with publish_status.console == ok)
  5. after the spike ends the alert RESOLVES
Everything runs in a temp dir on a spare port; all started processes are killed on exit.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PORT = int(os.environ.get("SMOKE_PORT", "8765"))
BASE = f"http://127.0.0.1:{PORT}"

# Fast timings so the whole run takes ~1 minute
TUNING = {
    # Dual-window like production, scaled down: 30 s main window + 10 s fast path
    "WINDOW_SECONDS": "30",
    "FAST_WINDOW_SECONDS": "10",
    "EVAL_INTERVAL_SEC": "1",
    "BASELINE_WARMUP_SAMPLES": "5",
    "MIN_EVENTS_IN_WINDOW": "10",
    "CONFIRM_TICKS": "2",
    "RESOLVE_TICKS": "3",
    "ALERT_COOLDOWN_SEC": "5",
    "TAIL_POLL_INTERVAL_SEC": "0.1",
    "SOURCE_RESCAN_SEC": "0.5",
}
EVAL = float(TUNING["EVAL_INTERVAL_SEC"])
CONFIRM = int(TUNING["CONFIRM_TICKS"])
LATENCY_BUDGET = EVAL + CONFIRM * EVAL + 1.0
SPIKE_SEC = 12

sys.path.insert(0, str(BACKEND))
from app.config import Settings  # noqa: E402
from app.detector import classify_severity  # noqa: E402


def log(msg: str) -> None:
    print(f"[smoke {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def start(cmd: list[str], env: dict, name: str, logdir: Path) -> subprocess.Popen:
    out = open(logdir / f"{name}.out", "wb")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    return subprocess.Popen(cmd, cwd=BACKEND, env=env, stdout=out, stderr=subprocess.STDOUT,
                            creationflags=flags)


async def wait_until(predicate, timeout: float, what: str, interval: float = 0.25):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = await predicate()
            if last:
                return last
        except (httpx.HTTPError, OSError):
            pass
        await asyncio.sleep(interval)
    raise AssertionError(f"timed out after {timeout}s waiting for {what} (last={last!r})")


async def run(tmp: Path) -> dict:
    results: dict = {}
    async with httpx.AsyncClient(base_url=BASE, timeout=5) as http:
        await wait_until(lambda: _ready(http), 30, "/api/ready == 200")
        log("backend ready")
        await wait_until(lambda: _baseline_ready(http), 60, "baseline warm-up")
        log("baseline ready")

        async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws", open_timeout=5) as ws:
            snapshot = json.loads(await asyncio.wait_for(ws.recv(), 5))
            assert snapshot["type"] == "snapshot", snapshot["type"]
            since = snapshot["seq"]

            r = await http.post("/api/sim/spike", json={
                "scenario": "spike", "error_ratio": 0.6, "duration_sec": SPIKE_SEC})
            r.raise_for_status()
            t0 = time.monotonic()
            log("spike triggered")

            opened = await _next_alert(ws, "OPENED", timeout=30)
            latency = round(time.monotonic() - t0, 2)
            results["alert_latency_sec"] = latency
            results["severity"] = opened["severity"]
            results["opened_by_window_sec"] = opened["window_seconds"]
            results["detection_latency_sec"] = opened.get("detection_latency_sec")
            log(f"OPENED {opened['severity']} z={opened['z_score']} rate={opened['error_rate']} "
                f"after {latency}s (budget {LATENCY_BUDGET}s)")
            assert latency <= LATENCY_BUDGET, f"alert latency {latency}s > budget {LATENCY_BUDGET}s"

            cfg = Settings(_env_file=None, **{k.lower(): v for k, v in TUNING.items()})
            expected = classify_severity(opened["z_score"], opened["error_rate"], cfg).name
            assert opened["severity"] == expected, f"severity {opened['severity']} != expected {expected}"
            assert opened["severity"] in ("MEDIUM", "HIGH", "CRITICAL"), "60% error spike should be >= MEDIUM"

            poll = (await http.get("/api/poll", params={"since_seq": since})).json()
            polled = [e["data"] for e in poll["envelopes"] if e["type"] == "alert"]
            assert any(a["id"] == opened["id"] and a["event"] == "OPENED" for a in polled), \
                "OPENED alert missing from /api/poll"
            assert poll["boot_id"] == snapshot["data"]["boot_id"]
            log("poll parity ok")

            status = await _publish_status(ws, opened["id"], timeout=10)
            assert status.get("console") == "ok", status
            results["publish_status"] = status
            log(f"publish status {status}")

            resolved = await _next_alert(ws, "RESOLVED", timeout=SPIKE_SEC + 45)
            assert resolved["id"] == opened["id"]
            results["peak_severity"] = resolved["peak_severity"]
            log(f"RESOLVED (peak {resolved['peak_severity']})")

        health = (await http.get("/api/health")).json()
        results["health_latency"] = health["latency"]
        assert health["publisher"]["published"] >= 2, health["publisher"]  # OPENED + RESOLVED
    return results


async def _ready(http):
    return (await http.get("/api/ready")).status_code == 200


async def _baseline_ready(http):
    return (await http.get("/api/health")).json()["baseline_ready"]


async def _next_alert(ws, event: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"no {event} alert over WebSocket within {timeout}s")
        msg = json.loads(await asyncio.wait_for(ws.recv(), remaining))
        if msg.get("type") == "alert" and msg["data"]["event"] == event:
            return msg["data"]


async def _publish_status(ws, alert_id: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError("no publish_status alert_update received")
        msg = json.loads(await asyncio.wait_for(ws.recv(), remaining))
        if msg.get("type") == "alert_update" and msg["data"]["id"] == alert_id \
                and "publish_status" in msg["data"]:
            return msg["data"]["publish_status"]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="accentra-smoke-"))
    logfile = tmp / "app.log"
    env = {**os.environ, **TUNING,
           "LOG_FILE_PATH": str(logfile), "LOG_SOURCES": "",
           "BASELINE_PATH": str(tmp / "baseline.json"),
           "PUBLISH_MODE": "dry_run", "ENABLE_SIM": "true", "PYTHONUNBUFFERED": "1"}
    procs = [
        start([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)], env, "backend", tmp),
        start([sys.executable, "-m", "simulator.generate_logs", "--file", str(logfile),
               "--rps", "40", "--base-error", "0.02"], env, "simulator", tmp),
    ]
    code = 1
    try:
        results = asyncio.run(run(tmp))
        log("PASS " + json.dumps(results))
        code = 0
    except Exception as exc:
        log(f"FAIL {type(exc).__name__}: {exc}")
        for name in ("backend", "simulator"):
            tail = (tmp / f"{name}.out").read_text(errors="replace").splitlines()[-15:]
            log(f"--- last lines of {name} ---\n" + "\n".join(tail))
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return code


if __name__ == "__main__":
    sys.exit(main())
