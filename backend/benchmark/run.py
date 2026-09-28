"""
Detector benchmark: which baseline and which window settings catch real incidents fastest
with the fewest false alarms?

    cd backend && python -m benchmark.run            # ~1-2 min, writes docs/detector-benchmark.{md,json}
    python -m benchmark.run --days 5 --seeds 7,11,23 --workers 6

How it works
------------
1. Synthesises DAYS of per-second traffic (seeded, reproducible) for two traffic levels:
   - the simulator's daily pattern (traffic curve, nightly batch 8% errors, morning peak 4%)
     which is *expected* behaviour and should not alert,
   - base noise at 2% errors,
   - short benign blips (15% errors for 20 s, self-healing) which should not alert,
   - injected incidents at known times which *should* alert:
     spike (35% for 2 min), moderate (12% for 4 min), ramp (2% → 25% over 10 min).
2. Replays the stream through the real `Evaluator` (same baseline, detector and
   alert-manager code as the live service) for every configuration.
3. Scores only the last 2 days, after every method (including the same-hour baseline,
   which needs 3 previous days) is warmed up:
   - caught: an alert OPENED between incident start and end + window + 60 s
   - delay: seconds from incident start to OPENED
   - false alarms/day: any other OPENED, split into expected-pattern hours, blips and noise
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import statistics
import tempfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from app.alerts import AlertManager
from app.baseline import make_baseline
from app.config import Settings
from app.detector import Detector
from app.evaluator import Evaluator
from app.window import SlidingWindow
from simulator.generate_logs import DAILY_PATTERN, daily_pattern

DAY = 86_400
SCORED_DAYS = 2
DOCS = Path(__file__).resolve().parents[2] / "docs"

WINDOWS = [
    # label, window_seconds, eval_interval_sec, confirm_ticks, fast_window_seconds
    ("60 s window · eval 5 s · 2 ticks", 60, 5, 2, 0),
    ("60 s window · 3 bad windows in a row", 60, 60, 3, 0),
    ("5 min window · eval every 1 min", 300, 60, 1, 0),
    ("5 min window · eval 5 s · 2 ticks", 300, 5, 2, 0),
    ("dual: 5 min + 60 s fast path (≥HIGH) · eval 5 s · 2 ticks", 300, 5, 2, 60),
]
BASELINES = [
    # label, method, seasonal
    ("EWMA mean/std", "ewma", False),
    ("median/MAD", "mad", False),
    ("median/MAD + same-hour", "mad", True),
]
TRAFFIC = [("high traffic (30 req/s)", 30.0), ("low traffic (2 req/s)", 2.0)]
INCIDENT_TYPES = ("spike", "moderate", "ramp")


@dataclass
class Event:
    kind: str  # spike | moderate | ramp | blip
    start: int
    end: int

    def error_ratio(self, t: int) -> float:
        if self.kind == "spike":
            return 0.35
        if self.kind == "moderate":
            return 0.12
        if self.kind == "blip":
            return 0.15
        return 0.02 + (0.25 - 0.02) * min(1.0, (t - self.start) / 600)  # ramp


def _pattern_windows(day_index: int) -> list[tuple[int, int]]:
    return [(day_index * DAY + int(s * DAY), day_index * DAY + int(e * DAY)) for s, e, _, _ in DAILY_PATTERN]


def _plan_events(days: int, rng: random.Random) -> list[Event]:
    """6 incidents + 4 blips per day, never overlapping each other or the expected pattern."""
    events: list[Event] = []
    for d in range(days):
        busy = [(s - 1800, e + 1800) for s, e in _pattern_windows(d)]
        kinds = list(INCIDENT_TYPES) * 2 + ["blip"] * 4
        rng.shuffle(kinds)
        for kind in kinds:
            length = {"spike": 120, "moderate": 240, "ramp": 900, "blip": 20}[kind]
            for _ in range(1000):
                start = d * DAY + rng.randrange(1800, DAY - 3600)
                end = start + length
                # 45 min clearance: alert cooldown + resolve + the longest window
                if all(end + 2700 < s or start > e + 2700 for s, e in busy):
                    events.append(Event(kind, start, end))
                    busy.append((start, end))
                    break
    return sorted(events, key=lambda e: e.start)


def synthesize(days: int, base_rps: float, seed: int) -> tuple[list[int], list[int], list[Event]]:
    """Prefix sums of per-second totals/errors, plus the event plan."""
    rng = random.Random(seed)
    events = _plan_events(days, rng)
    ev_iter, current = iter(events), None
    nxt = next(ev_iter, None)
    totals, errors = [0], [0]
    for t in range(days * DAY):
        while nxt and t >= nxt.start:
            current, nxt = nxt, next(ev_iter, None)
        if current and t >= current.end:
            current = None
        pattern_err, mult = daily_pattern(t, DAY)
        p = 0.02 if pattern_err is None else pattern_err
        if current:
            p = max(p, current.error_ratio(t))
        mu = base_rps * mult
        n = max(0, round(rng.gauss(mu, mu ** 0.5)))  # ~Poisson arrivals
        e = rng.binomialvariate(n, p) if n else 0
        totals.append(totals[-1] + n)
        errors.append(errors[-1] + e)
    return totals, errors, events


def replay(args) -> dict:
    (w_label, window, every, confirm, fast), (b_label, method, seasonal), (t_label, rps), days, seed = args
    totals, errors, events = synthesize(days, rps, seed)
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Settings(
            _env_file=None,
            window_seconds=window, fast_window_seconds=fast, eval_interval_sec=every, confirm_ticks=confirm,
            baseline_method=method, seasonal_enabled=seasonal,
            seasonal_day_seconds=DAY, baseline_path=str(Path(tmp) / "b.json"),
        )
        ev = Evaluator(cfg, SlidingWindow(window), make_baseline(cfg), Detector(cfg),
                       AlertManager(cfg, window_seconds=window),
                       fast_baseline=make_baseline(cfg, ".fast") if fast else None)
        opened: list[tuple[int, str]] = []
        for t in range(window, days * DAY + 1, int(every)):
            snap = _snap(totals, errors, t, window)
            fast_snap = _snap(totals, errors, t, fast) if fast else None
            for alert in ev.step(float(t), snap, fast_snap).alerts:
                if alert.event == "OPENED":
                    opened.append((t, alert.severity))
    return score(opened, events, days, window) | {
        "window": w_label, "baseline": b_label, "traffic": t_label}


def _snap(totals: list[int], errors: list[int], t: int, window: int) -> dict:
    total = totals[t] - totals[t - window]
    errs = errors[t] - errors[t - window]
    return {"total": total, "errors": errs, "warnings": 0,
            "error_rate": errs / total if total else 0.0, "events_per_sec": total / window}


def score(opened: list[tuple[int, str]], events: list[Event], days: int, window: int) -> dict:
    lo = (days - SCORED_DAYS) * DAY
    grace = window + 60
    incidents = [e for e in events if e.kind != "blip" and e.start >= lo]
    blips = [e for e in events if e.kind == "blip" and e.start >= lo]
    patterns = [w for d in range(days - SCORED_DAYS, days) for w in _pattern_windows(d)]
    scored_opens = [(t, s) for t, s in opened if t >= lo]

    used: set[int] = set()
    delays: dict[str, list[float]] = {k: [] for k in INCIDENT_TYPES}
    missed = 0
    for inc in incidents:
        hit = next((t for t, _ in scored_opens if inc.start <= t <= inc.end + grace and t not in used), None)
        if hit is None:
            missed += 1
        else:
            used.add(hit)
            delays[inc.kind].append(hit - inc.start)

    fa = {"expected_pattern": 0, "blip": 0, "noise": 0}
    for t, _ in scored_opens:
        if t in used or any(inc.start <= t <= inc.end + grace for inc in incidents):
            continue  # a re-open during an incident is not a false alarm
        if any(s <= t <= e + grace for s, e in patterns):
            fa["expected_pattern"] += 1
        elif any(b.start <= t <= b.end + grace for b in blips):
            fa["blip"] += 1
        else:
            fa["noise"] += 1

    return {"incidents": len(incidents), "caught": len(incidents) - missed,
            "delays": delays, "fa": fa, "scored_days": SCORED_DAYS}


def summarize(runs: list[dict]) -> dict:
    """Pool raw results of several seeds (more incidents → steadier numbers)."""
    delays = {k: [d for r in runs for d in r["delays"][k]] for k in INCIDENT_TYPES}
    all_delays = [d for ds in delays.values() for d in ds]
    days = sum(r["scored_days"] for r in runs)
    fa = {k: sum(r["fa"][k] for r in runs) for k in runs[0]["fa"]}
    return {
        "window": runs[0]["window"], "baseline": runs[0]["baseline"], "traffic": runs[0]["traffic"],
        "incidents": sum(r["incidents"] for r in runs),
        "caught": sum(r["caught"] for r in runs),
        "median_delay_sec": round(statistics.median(all_delays), 1) if all_delays else None,
        "max_delay_sec": max(all_delays) if all_delays else None,
        "delay_by_type": {k: round(statistics.median(v), 1) if v else None for k, v in delays.items()},
        "false_alarms_per_day": {k: round(v / days, 1) for k, v in fa.items()},
        "false_alarms_per_day_total": round(sum(fa.values()) / days, 1),
        "scored_days": days,
    }


def to_markdown(results: list[dict], days: int, seeds: list[int]) -> str:
    out = [
        "# Detector benchmark",
        "",
        f"Generated by `python -m benchmark.run --days {days} --seeds {','.join(map(str, seeds))}` "
        f"({len(seeds)} independent {days}-day runs pooled per row). Synthetic traffic "
        "with the simulator's daily pattern (nightly batch 02:00–03:30 at 8% errors, morning "
        "peak 09:00–11:00 at 4%), 2% background errors, 4 benign 20 s blips/day and 6 injected "
        f"incidents/day (spike 35%/2 min, moderate 12%/4 min, ramp 2→25%/10 min). Scored on the "
        f"last {SCORED_DAYS} days of each run. Same detector code as the live service.",
        "",
        "False alarms/day are split into **pattern** (the expected nightly batch / morning peak "
        "hours), **blip** (short self-healing bursts) and **noise**.",
        "",
    ]
    for t_label, _ in TRAFFIC:
        out += [f"## {t_label}", "",
                "| Window | Baseline | Caught | Median delay | Spike / moderate / ramp delay | False alarms/day (pattern / blip / noise) |",
                "|---|---|---|---|---|---|"]
        for r in (r for r in results if r["traffic"] == t_label):
            fa = r["false_alarms_per_day"]
            out.append(
                f"| {r['window']} | {r['baseline']} | {r['caught']}/{r['incidents']} | "
                f"{_s(r['median_delay_sec'])} | "
                f"{' / '.join(_s(r['delay_by_type'][k]) for k in INCIDENT_TYPES)} | "
                f"**{r['false_alarms_per_day_total']}** ({fa['expected_pattern']} / {fa['blip']} / {fa['noise']}) |")
        rows = [r for r in results if r["traffic"] == t_label]
        quietest, fastest = _best(rows), _fastest_quiet(rows)
        out += [""]
        if quietest:
            out.append(f"- Fewest false alarms (among configs that catch the most incidents): "
                       f"**{quietest['window']} + {quietest['baseline']}**")
        if fastest:
            out.append(f"- Fastest with ≤ {QUIET_FA_PER_DAY} false alarms/day and every incident "
                       f"caught: **{fastest['window']} + {fastest['baseline']}** "
                       f"({_s(fastest['median_delay_sec'])} median, spikes in "
                       f"{_s(fastest['delay_by_type']['spike'])})")
        out.append("")
    return "\n".join(out) + "\n"


def _s(v) -> str:
    return "–" if v is None else f"{v:g} s"


QUIET_FA_PER_DAY = 0.5


def _best(rows: list[dict]) -> dict | None:
    most = max((r["caught"] for r in rows), default=0)
    full = [r for r in rows if r["caught"] == most]
    return min(full, key=lambda r: (r["false_alarms_per_day_total"], r["median_delay_sec"] or 1e9), default=None)


def _fastest_quiet(rows: list[dict]) -> dict | None:
    ok = [r for r in rows if r["caught"] == r["incidents"] and r["false_alarms_per_day_total"] <= QUIET_FA_PER_DAY]
    return min(ok, key=lambda r: r["median_delay_sec"] or 1e9, default=None)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--days", type=int, default=5)
    ap.add_argument("--seeds", default="7,11,23", help="comma-separated; results are pooled")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", type=Path, default=DOCS)
    a = ap.parse_args()

    seeds = [int(s) for s in a.seeds.split(",")]
    combos = list(itertools.product(TRAFFIC, WINDOWS, BASELINES))
    jobs = [(w, b, t, a.days, seed) for t, w, b in combos for seed in seeds]
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        raw = list(pool.map(replay, jobs))
    results = [summarize(raw[i:i + len(seeds)]) for i in range(0, len(raw), len(seeds))]

    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "detector-benchmark.json").write_text(
        json.dumps({"days": a.days, "seeds": seeds, "results": results}, indent=2), encoding="utf-8")
    md = to_markdown(results, a.days, seeds)
    (a.out / "detector-benchmark.md").write_text(md, encoding="utf-8")
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(md)


if __name__ == "__main__":
    main()
