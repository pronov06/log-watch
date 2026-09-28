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
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
         f"{random.randint(0, 999):03d}Z"

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
    batch_size = max(1, int(rps / 5))  # Write in batches ~5 times per second

    try:
        while True:
            elapsed = time.time() - start_time

            # Determine current error ratio
            current_error = base_error

            # Check scheduled scenario
            if scenario and elapsed >= scenario_at:
                scenario_elapsed = elapsed - scenario_at
                if scenario_elapsed < scenario_duration:
                    current_error = _apply_scenario(
                        scenario, base_error, scenario_error_ratio,
                        scenario_elapsed, scenario_duration,
                    )

            # Check real-time control file (from UI button)
            current_error = _check_control(
                control_path, current_error, base_error, scenario_error_ratio,
            )

            # Add a small sine-wave pattern (fake daily fluctuation)
            sine_factor = 1.0 + 0.1 * math.sin(elapsed * 2 * math.pi / 300)
            actual_rps = rps * sine_factor

            # Generate and write a batch
            lines = []
            for _ in range(batch_size):
                lines.append(generate_line(error_ratio=current_error))

            with open(path, "a", encoding="utf-8") as f:
                for line in lines:
                    f.write(line + "\n")
                f.flush()

            line_count += len(lines)

            if line_count % 100 == 0:
                print(f"[Simulator] {line_count} lines written, error_ratio={current_error:.2%}, elapsed={elapsed:.0f}s")

            # Sleep to match target rps
            sleep_time = batch_size / actual_rps
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print(f"\n[Simulator] Stopped after {line_count} lines")


def _apply_scenario(
    scenario: str,
    base_error: float,
    spike_error: float,
    elapsed: float,
    duration: float,
) -> float:
    """Apply a named anomaly scenario."""
    if scenario == "spike":
        return spike_error
    elif scenario == "ramp":
        # Gradually increase error rate
        progress = min(elapsed / duration, 1.0)
        return base_error + (spike_error - base_error) * progress
    elif scenario == "flood":
        # High volume with moderate errors
        return base_error * 3
    elif scenario == "outage":
        if elapsed < duration * 0.7:
            return 0.95  # Almost all errors
        else:
            return 0.0  # Then silence (no lines)
    elif scenario == "flapping":
        # Alternate between spike and normal every 15 seconds
        cycle = int(elapsed / 15)
        return spike_error if cycle % 2 == 0 else base_error
    else:
        return base_error


def _check_control(
    control_path: Path,
    current_error: float,
    base_error: float,
    spike_error: float,
) -> float:
    """Check the sim_control.json file for real-time commands from the UI."""
    if not control_path.exists():
        return current_error

    try:
        data = json.loads(control_path.read_text(encoding="utf-8"))
        action = data.get("action", "")

        if action == "spike":
            error_ratio = data.get("error_ratio", spike_error)
            duration = data.get("duration_sec", 60)
            started = data.get("started_at", 0)

            if started and (time.time() - started) > duration:
                # Spike expired, auto-recover
                control_path.write_text(
                    json.dumps({"action": "recover"}), encoding="utf-8"
                )
                return base_error
            return error_ratio

        elif action == "recover":
            return base_error

    except (json.JSONDecodeError, OSError):
        pass

    return current_error


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Log traffic generator")
    parser.add_argument("--file", default="./data/app.log", help="Output log file path")
    parser.add_argument("--rps", type=float, default=30, help="Lines per second")
    parser.add_argument("--base-error", type=float, default=0.02, help="Base error ratio (0-1)")
    parser.add_argument("--scenario", choices=["spike", "ramp", "flood", "outage", "flapping"],
                        help="Anomaly scenario to inject")
    parser.add_argument("--at", type=float, default=30, help="Seconds after start to begin scenario")
    parser.add_argument("--duration", type=float, default=60, help="Scenario duration in seconds")
    parser.add_argument("--error-ratio", type=float, default=0.35, help="Error ratio during scenario")

    args = parser.parse_args()

    run_generator(
        file_path=args.file,
        rps=args.rps,
        base_error=args.base_error,
        scenario=args.scenario,
        scenario_at=args.at,
        scenario_duration=args.duration,
        scenario_error_ratio=args.error_ratio,
    )


if __name__ == "__main__":
    main()
