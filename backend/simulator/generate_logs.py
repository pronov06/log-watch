"""
Log traffic generator and anomaly injector.

Generates realistic log lines and appends them to the log file.
Supports injectable anomaly scenarios for testing and live demos.

Usage:
  python -m simulator.generate_logs --file ./data/app.log --rps 30 --base-error 0.02
  python -m simulator.generate_logs ... --scenario spike --at 120 --duration 60 --error-ratio 0.35

The simulator also watches a control file (data/sim_control.json) so the
frontend's "Simulate Spike" button can trigger anomalies in real time.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Realistic message templates
# ---------------------------------------------------------------------------

SERVICES = ["auth", "payments", "orders", "search", "gateway"]
SERVICE_WEIGHTS = [0.15, 0.25, 0.20, 0.15, 0.25]

INFO_MESSAGES = [
    "Request processed successfully",
    "User login successful",
    "Cache hit for key={key}",
    "Health check passed",
    "Connection pool: {n} active, {m} idle",
    "Processed batch of {n} records",
    "Session created for user={user}",
    "API response: 200 OK latency={lat}ms",
    "Background job completed in {lat}ms",
    "Config reloaded successfully",
]

WARNING_MESSAGES = [
    "Slow query detected: {lat}ms",
    "Connection pool nearing capacity: {n}/{m}",
    "Rate limit approaching for client={client}",
    "Deprecated API version used",
    "Retry attempt {n} for upstream call",
    "Memory usage at {pct}%",
    "Disk usage at {pct}%",
]

ERROR_MESSAGES = [
    "DB connection timeout after {lat}ms",
    "NullPointerException in OrderService.process()",
    "Upstream 502 from inventory service",
    "Payment gateway timeout: transaction={txn}",
    "Authentication failed: invalid token",
    "Circuit breaker OPEN for payments-service",
    "Out of memory: heap space exceeded",
    "Connection refused: redis://cache:6379",
    "SSL handshake failed with upstream",
    "Request timeout after 30s: /api/orders/{id}",
    "Database deadlock detected on table=orders",
    "Failed to serialize response: encoding error",
]

# Per-service error propensity (higher = more errors under normal conditions)
SERVICE_ERROR_WEIGHT = {
    "auth": 0.8,
    "payments": 1.5,
    "orders": 1.2,
    "search": 0.5,
    "gateway": 1.0,
}


def _random_val() -> dict:
    """Generate random template values."""
    return {
        "key": f"user:{random.randint(1000, 9999)}",
        "n": random.randint(1, 100),
        "m": random.randint(50, 200),
        "user": f"user_{random.randint(1, 500)}",
        "lat": random.randint(10, 5000),
        "client": f"client_{random.randint(1, 20)}",
        "pct": random.randint(60, 95),
        "txn": f"TXN{random.randint(100000, 999999)}",
        "id": random.randint(1, 99999),
    }


def _gen_message(templates: list[str]) -> str:
    """Pick a random template and fill in values."""
    tmpl = random.choice(templates)
    try:
        return tmpl.format(**_random_val())
    except (KeyError, IndexError):
        return tmpl


def _pick_service() -> str:
    return random.choices(SERVICES, weights=SERVICE_WEIGHTS, k=1)[0]


def generate_line(error_ratio: float = 0.02, warn_ratio: float = 0.05) -> str:
    """
    Generate a single realistic log line.

    error_ratio and warn_ratio control the probability of ERROR and WARNING
    levels respectively. The remaining probability is INFO.
    """
    # Real millisecond timestamp: the backend's ingest-lag metric is computed from it
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    service = _pick_service()
    r = random.random()

    # Adjust error probability by service
    adjusted_error = error_ratio * SERVICE_ERROR_WEIGHT.get(service, 1.0)

    if r < adjusted_error:
        level = "ERROR"
        msg = _gen_message(ERROR_MESSAGES)
    elif r < adjusted_error + warn_ratio:
        level = "WARNING"
        msg = _gen_message(WARNING_MESSAGES)
    else:
        level = "INFO"
        msg = _gen_message(INFO_MESSAGES)

    latency = random.randint(5, 200) if level == "INFO" else random.randint(100, 5000)

    return f'{ts} {level:<7s} service={service} msg="{msg}" latency_ms={latency}'


def run_generator(
    file_path: str,
    rps: float = 30,
    base_error: float = 0.02,
    scenario: str | None = None,
    scenario_at: float = 0,
    scenario_duration: float = 60,
    scenario_error_ratio: float = 0.35,
    daily_pattern_enabled: bool = False,
    day_seconds: float = 86_400,
):
    """
    Main generator loop.

    Writes log lines to file_path at approximately rps lines/second.
    Supports anomaly scenarios and real-time control via sim_control.json.
    """
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    control_path = path.parent / "sim_control.json"
    start_time = time.time()

    print(f"[Simulator] Writing to {path} at ~{rps} rps, base error={base_error:.1%}")
    if scenario:
        print(f"[Simulator] Scenario '{scenario}' at t+{scenario_at}s for {scenario_duration}s")

    line_count = 0

    try:
        while True:
            elapsed = time.time() - start_time

            # Determine current error ratio and volume multiplier
            current_error, rps_mult = base_error, 1.0
            if daily_pattern_enabled:
                pattern_error, rps_mult = daily_pattern(time.time(), day_seconds)
                if pattern_error is not None:
                    current_error = max(current_error, pattern_error)

            # Check scheduled scenario
            if scenario and elapsed >= scenario_at:
                scenario_elapsed = elapsed - scenario_at
                if scenario_elapsed < scenario_duration:
                    current_error, rps_mult = _apply_scenario(
                        scenario, base_error, scenario_error_ratio,
                        scenario_elapsed, scenario_duration,
                    )

            # Real-time control file (UI button) overrides the schedule while active
            control = _check_control(control_path, base_error, scenario_error_ratio)
            if control is not None:
                current_error, rps_mult = control

            if rps_mult <= 0:  # outage tail: the service has gone silent
                time.sleep(0.2)
                continue

            # Add a small sine-wave pattern (fake daily fluctuation)
            sine_factor = 1.0 + 0.1 * math.sin(elapsed * 2 * math.pi / 300)
            actual_rps = rps * rps_mult * sine_factor
            batch_size = max(1, int(actual_rps / 5))  # write ~5 batches per second

            lines = [generate_line(error_ratio=current_error) for _ in range(batch_size)]
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
                f.flush()

            prev = line_count
            line_count += len(lines)
            if line_count // 500 != prev // 500:
                print(f"[Simulator] {line_count} lines written, error_ratio={current_error:.2%}, "
                      f"rps={actual_rps:.0f}, elapsed={elapsed:.0f}s", flush=True)

            time.sleep(batch_size / actual_rps)

    except KeyboardInterrupt:
        print(f"\n[Simulator] Stopped after {line_count} lines")


SCENARIOS = ("spike", "ramp", "flood", "outage", "flapping")


# Recurring, *expected* behaviour in a day (fractions of the day, UTC-aligned so the
# backend's same-hour slots line up with it):
#   02:00-03:30  nightly batch job: 8% errors (retries against a cold cache)
#   09:00-11:00  morning peak: 4% errors (load-related timeouts)
#   traffic follows a daily curve: lowest at 00:00, 1.4x at 12:00
DAILY_PATTERN = ((2 / 24, 3.5 / 24, 0.08, "nightly batch"), (9 / 24, 11 / 24, 0.04, "morning peak"))


def daily_pattern(t: float, day_seconds: float = 86_400) -> tuple[float | None, float]:
    """Return (error_ratio or None, rps_multiplier) for epoch time `t`."""
    frac = (t % day_seconds) / day_seconds
    rps_mult = 1.0 - 0.4 * math.cos(2 * math.pi * frac)  # 0.6x at midnight, 1.4x at noon
    for start, end, err, _name in DAILY_PATTERN:
        if start <= frac < end:
            return err, rps_mult
    return None, rps_mult


def _apply_scenario(
    scenario: str,
    base_error: float,
    spike_error: float,
    elapsed: float,
    duration: float,
) -> tuple[float, float]:
    """Return (error_ratio, rps_multiplier) for a named anomaly scenario at `elapsed` seconds."""
    if scenario == "spike":
        return spike_error, 1.0
    if scenario == "ramp":
        progress = min(elapsed / duration, 1.0)
        return base_error + (spike_error - base_error) * progress, 1.0
    if scenario == "flood":
        # Volume x10 with somewhat more errors (retries and timeouts under load)
        return min(1.0, base_error * 3), 10.0
    if scenario == "outage":
        # Hard failure: nearly everything errors, then the service stops logging entirely
        return (0.95, 1.0) if elapsed < duration * 0.7 else (base_error, 0.0)
    if scenario == "flapping":
        cycle = int(elapsed / 15)
        return (spike_error if cycle % 2 == 0 else base_error), 1.0
    return base_error, 1.0


def _check_control(
    control_path: Path,
    base_error: float,
    spike_error: float,
) -> tuple[float, float] | None:
    """
    Read sim_control.json (written by POST /api/sim/spike from the UI).

    Returns (error_ratio, rps_multiplier) while a scenario is active, else None.
    """
    if not control_path.exists():
        return None
    try:
        data = json.loads(control_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None  # mid-write; try again next batch

    if data.get("action") != "spike":
        return None

    duration = float(data.get("duration_sec", 60))
    elapsed = time.time() - float(data.get("started_at", 0) or 0)
    if elapsed > duration:
        try:
            control_path.write_text(json.dumps({"action": "recover"}), encoding="utf-8")
        except OSError:
            pass
        return None

    return _apply_scenario(
        data.get("scenario", "spike"), base_error,
        float(data.get("error_ratio", spike_error)), elapsed, duration,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Log traffic generator")
    parser.add_argument("--file", default="./data/app.log", help="Output log file path")
    parser.add_argument("--rps", type=float, default=30, help="Lines per second")
    parser.add_argument("--base-error", type=float, default=0.02, help="Base error ratio (0-1)")
    parser.add_argument("--scenario", choices=SCENARIOS,
                        help="Anomaly scenario to inject")
    parser.add_argument("--at", type=float, default=30, help="Seconds after start to begin scenario")
    parser.add_argument("--duration", type=float, default=60, help="Scenario duration in seconds")
    parser.add_argument("--error-ratio", type=float, default=0.35, help="Error ratio during scenario")

    parser.add_argument("--daily-pattern", action="store_true",
                        help="Add the recurring daily pattern (nightly batch + morning peak errors, traffic curve)")
    parser.add_argument("--day-seconds", type=float, default=86_400,
                        help="Length of a simulated day; e.g. 600 compresses a day into 10 minutes for demos "
                             "(set SEASONAL_DAY_SECONDS to the same value on the backend)")
    args = parser.parse_args()

    run_generator(
        file_path=args.file,
        rps=args.rps,
        base_error=args.base_error,
        scenario=args.scenario,
        scenario_at=args.at,
        scenario_duration=args.duration,
        scenario_error_ratio=args.error_ratio,
        daily_pattern_enabled=args.daily_pattern,
        day_seconds=args.day_seconds,
    )


if __name__ == "__main__":
    main()
