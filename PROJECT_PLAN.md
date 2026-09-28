# Real-Time Log Anomaly Detector with Alert Feed: Full Build Plan

> **How to use this document:** Give this entire file to a coding agent (Claude Code, Cursor, etc.) as its spec. Tell it: *"Implement this project phase by phase. Complete each phase's acceptance criteria before moving on. Ask me only if something is truly ambiguous."*

---

## 0. TL;DR

A Python service tails a continuously growing log file, computes a **rolling error rate** over a **sliding window**, learns a **baseline** of normal behavior, flags **statistical deviations**, assigns **severity levels** (LOW / MEDIUM / HIGH / CRITICAL), streams everything to a **React dashboard in real time (WebSockets, with polling fallback)**, and **pushes alerts to AWS CloudWatch Logs and SNS**.

A **log generator/simulator** with injectable anomalies makes the demo reliable and testable.

---

## 1. Goals, Non-Goals, Success Criteria

### Must-have (maps 1:1 to the problem statement)
| # | Requirement | Where it lives |
|---|---|---|
| R1 | Monitor a continuously growing log file | `tailer.py` |
| R2 | Rolling error rate with sliding window | `window.py` |
| R3 | Baseline of normal behavior | `baseline.py` |
| R4 | Detect deviations from baseline | `detector.py` |
| R5 | Severity levels | `detector.py` + `severity.py` |
| R6 | Real-time frontend (WebSockets or polling) | `api/ws.py` + `frontend/` |
| R7 | Alerts displayed as generated | `AlertFeed` component |
| R8 | Push to CloudWatch Logs or SNS | `publishers/` |

### Nice-to-have (only after all must-haves work)
- Per-service breakdown of error rate
- Throughput (volume) anomaly detector (spike or drop)
- Alert acknowledge / resolve lifecycle
- Top error messages panel (log signature clustering)
- CloudWatch custom metric + alarm
- Dark mode, sound/toast notifications
- Docker Compose one-command startup

### Success criteria for the demo
1. Start everything with one command.
2. Dashboard shows a live error-rate chart with a baseline band.
3. Trigger a spike (button or CLI). Within about 10 seconds an alert appears in the feed with the right severity.
4. Same alert shows up in AWS CloudWatch Logs (and an SNS email/SMS).
5. When the spike ends, the alert auto-resolves.

---

## 2. Architecture

```
┌────────────────┐   appends lines    ┌───────────────────────────────────────────────────────────┐
│ Log Generator  │ ─────────────────► │                     app.log (growing file)                │
│ (simulator.py) │                    └───────────────┬───────────────────────────────────────────┘
└────────────────┘                                    │ tail (offset polling, rotation-safe)
        ▲                                             ▼
        │ POST /api/sim/*        ┌──────────────────────────────────────────────┐
        │ (trigger anomaly)      │               BACKEND (FastAPI, asyncio)     │
        │                        │                                              │
┌───────┴────────┐               │  Tailer ─► Parser ─► SlidingWindow           │
│ React Frontend │ ◄── WS /ws ───│                          │                   │
│  (Vite + TS)   │ ◄── REST ─────│                          ▼                   │
│  - Live chart  │               │            Baseline (EWMA mean/std)          │
│  - Alert feed  │               │                          │                   │
│  - Log tail    │               │                          ▼                   │
└────────────────┘               │           Detector (z-score + rules)         │
                                 │                          │                   │
                                 │                          ▼                   │
                                 │      AlertManager (dedupe, lifecycle,        │
                                 │      cooldown, escalation)                   │
                                 │         │                │                   │
                                 │         ▼                ▼                   │
                                 │  Event Bus ──► WS broadcaster / poll buffer  │
                                 │         │                                    │
                                 │         ▼                                    │
                                 │  Publisher Queue ─► CloudWatch Logs          │
                                 │  (async, retry)  └► SNS Topic ─► email/SMS   │
                                 └──────────────────────────────────────────────┘
```

### Runtime model
One Python process, one asyncio event loop, several cooperating tasks:

1. **tailer task**: reads new lines, parses them, pushes to the window (every ~200 ms)
2. **evaluator task**: every `EVAL_INTERVAL_SEC` (default 5 s) computes the metric, updates the baseline, runs the detector, and emits events
3. **publisher task**: consumes the alert queue and calls AWS (boto3 in a thread executor, with retry and backoff)
4. **WebSocket broadcaster**: fan-out of events to connected clients
5. **FastAPI** serves REST and WS

### Event flow (all messages share one envelope)
```json
{ "type": "metric|alert|baseline|log|snapshot|heartbeat", "seq": 1042, "ts": "2026-09-28T10:00:05Z", "data": { } }
```
`seq` is a monotonically increasing integer. It powers polling (`?since_seq=`) and lets the client detect gaps.

---

## 3. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Required |
| API | FastAPI + Uvicorn | Native async and WebSocket support |
| Config | `pydantic-settings` (`.env`) | Typed config |
| AWS | `boto3` (CloudWatch Logs, SNS, optional CloudWatch metrics) | Official SDK |
| Testing | `pytest`, `pytest-asyncio`, `moto` | Mock AWS locally |
| Frontend | React 18 + Vite + TypeScript | Fast dev, typed |
| Charts | Recharts | Easy area, line and reference-area charts |
| Styling | Tailwind CSS | Speed |
| Infra | Docker Compose (+ optional LocalStack) | One-command demo |

`requirements.txt`:
```
fastapi
uvicorn[standard]
pydantic
pydantic-settings
boto3
python-dotenv
pytest
pytest-asyncio
moto[logs,sns]
httpx
```

---

## 4. Repository Layout

```
log-anomaly-detector/
├── README.md
├── docker-compose.yml
├── .env.example
├── Makefile
├── backend/
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py              # FastAPI app factory, lifespan starts tasks
│   │   ├── config.py            # Settings (pydantic-settings)
│   │   ├── models.py            # Pydantic models: LogEvent, MetricPoint, Alert, Envelope
│   │   ├── pipeline.py          # Orchestrates tailer/window/baseline/detector loop
│   │   ├── tailer.py            # Async file tailer
│   │   ├── parser.py            # Text and JSON log parsing
│   │   ├── window.py            # Time-bucketed sliding window
│   │   ├── baseline.py          # EWMA baseline with warm-up + freeze
│   │   ├── detector.py          # Anomaly logic + severity mapping
│   │   ├── alerts.py            # AlertManager (lifecycle, dedupe, cooldown)
│   │   ├── bus.py               # In-memory pub/sub + ring buffer with seq
│   │   ├── api/
│   │   │   ├── routes.py        # REST endpoints
│   │   │   └── ws.py            # WebSocket endpoint
│   │   └── publishers/
│   │       ├── base.py          # Publisher protocol
│   │       ├── cloudwatch.py    # CloudWatch Logs publisher
│   │       ├── sns.py           # SNS publisher
│   │       ├── console.py       # Dry-run publisher (logs to stdout)
│   │       └── dispatcher.py    # Queue, retry, routing by severity
│   ├── simulator/
│   │   └── generate_logs.py     # Traffic generator + anomaly injection CLI
│   └── tests/
│       ├── test_parser.py
│       ├── test_window.py
│       ├── test_baseline.py
│       ├── test_detector.py
│       ├── test_alerts.py
│       ├── test_publishers.py
│       └── test_e2e.py
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── Dockerfile
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── types.ts
│       ├── hooks/useLiveFeed.ts     # WS with auto-reconnect + polling fallback
│       ├── components/
│       │   ├── Header.tsx           # Title + connection status pill
│       │   ├── KpiCards.tsx         # Current rate, baseline, z-score, active alerts
│       │   ├── ErrorRateChart.tsx   # Line + baseline band + anomaly shading
│       │   ├── AlertFeed.tsx        # Live list with severity badges
│       │   ├── AlertToast.tsx
│       │   ├── LogTail.tsx          # Last ~100 log lines, errors highlighted
│       │   └── SimControls.tsx      # Buttons: trigger spike / recover
│       └── lib/format.ts
└── infra/
    ├── aws-setup.sh                 # Creates log group, stream, SNS topic, subscription
    ├── iam-policy.json
    └── cloudformation.yaml          # (optional) same resources as IaC
```

---

## 5. Configuration (`.env.example`)

```ini
# --- Input ---
LOG_FILE_PATH=./data/app.log
LOG_FORMAT=auto                 # auto | text | json
TAIL_POLL_INTERVAL_SEC=0.2

# --- Windowing ---
WINDOW_SECONDS=60               # sliding window length
EVAL_INTERVAL_SEC=5             # how often we compute and emit a metric
MIN_EVENTS_IN_WINDOW=20         # below this, error rate is "unreliable": skip detection

# --- Baseline ---
BASELINE_WARMUP_SAMPLES=24      # 24 x 5s = 2 min of learning before detection starts
BASELINE_ALPHA=0.05             # EWMA smoothing factor
BASELINE_MIN_STD=0.01           # std floor (1 percentage point) so flat baselines don't explode z
FREEZE_BASELINE_DURING_ALERT=true

# --- Detection thresholds ---
Z_LOW=3.0
Z_MEDIUM=4.5
Z_HIGH=6.5
Z_CRITICAL=9.0
ABS_RATE_CRITICAL=0.50          # 50%+ error rate is always CRITICAL
MIN_ABS_RATE=0.05               # rate must also exceed 5% to alert (avoids noise at ~0% baseline)
CONFIRM_TICKS=2                 # consecutive breaching ticks before opening an alert
RESOLVE_Z=2.0
RESOLVE_TICKS=3                 # consecutive calm ticks before resolving
ALERT_COOLDOWN_SEC=120          # min time before re-opening after resolve (flap protection)

# --- Alert publishing ---
PUBLISH_MODE=dry_run            # dry_run | aws
AWS_REGION=ap-south-1
CW_LOG_GROUP=/hackathon/log-anomaly-detector
CW_LOG_STREAM=alerts
SNS_TOPIC_ARN=arn:aws:sns:ap-south-1:123456789012:log-anomaly-alerts
SNS_MIN_SEVERITY=MEDIUM         # only page humans for MEDIUM and above
AWS_ENDPOINT_URL=               # set to http://localstack:4566 for LocalStack

# --- API ---
CORS_ORIGINS=http://localhost:5173
RING_BUFFER_SIZE=2000
```

---

## 6. Core Algorithms (the important part)

### 6.1 Log line formats supported

**Text:**
```
2026-09-28T10:15:03.412Z ERROR service=payments msg="DB connection timeout" latency_ms=5021
2026-09-28T10:15:03.500Z INFO  service=auth msg="login ok" latency_ms=42
```
**JSON lines:**
```json
{"ts":"2026-09-28T10:15:03.412Z","level":"ERROR","service":"payments","msg":"DB connection timeout"}
```

`parser.parse_line(line) -> LogEvent | None`
- `auto` mode: if the line starts with `{`, try JSON, otherwise text regex
- Extract: `ts` (fallback to `now()` if missing or unparseable), `level`, `service` (default `"unknown"`), `message`
- Normalize levels: `WARN→WARNING`, `FATAL/CRITICAL→ERROR`. **Errors = ERROR + FATAL/CRITICAL.**
- Malformed lines are counted (`parse_failures` metric) and skipped, never raised
- Use **processing time** for bucketing (simple and robust). Keep the event timestamp for display.

### 6.2 Tailer (R1)
- Async loop that opens the file, seeks to **end** on first start (configurable `--from-start`), then polls every `TAIL_POLL_INTERVAL_SEC`
- Track offset. On each poll: `stat()` the file.
  - `size < offset` means truncated, so reset offset to 0
  - `inode` changed means rotated, so reopen from 0
- Buffer partial last line (no trailing `\n`) until it completes
- If the file doesn't exist yet, wait and retry (don't crash)
- Read in chunks (e.g. up to 1 MB per poll) to avoid blocking the loop
- Yield lines via an `asyncio.Queue` (bounded, drop-oldest with a counter if the consumer lags)

### 6.3 Sliding window (R2)

Time-bucketed ring buffer with **1-second buckets**. O(window) memory, O(1) per event.

```python
# window.py
from collections import deque
from dataclasses import dataclass
import time

@dataclass
class Bucket:
    sec: int
    total: int = 0
    errors: int = 0
    warnings: int = 0

class SlidingWindow:
    def __init__(self, window_seconds: int):
        self.window = window_seconds
        self.buckets: deque[Bucket] = deque()

    def add(self, level: str, now: float | None = None):
        sec = int(now or time.time())
        if not self.buckets or self.buckets[-1].sec != sec:
            self.buckets.append(Bucket(sec))
        b = self.buckets[-1]
        b.total += 1
        if level == "ERROR": b.errors += 1
        elif level == "WARNING": b.warnings += 1

    def _evict(self, now: int):
        cutoff = now - self.window
        while self.buckets and self.buckets[0].sec <= cutoff:
            self.buckets.popleft()

    def snapshot(self, now: float | None = None):
        now_i = int(now or time.time())
        self._evict(now_i)
        total = sum(b.total for b in self.buckets)
        errors = sum(b.errors for b in self.buckets)
        return {
            "total": total,
            "errors": errors,
            "error_rate": (errors / total) if total else 0.0,
            "events_per_sec": total / self.window,
        }
```
Also keep a **per-service** window dict (`dict[str, SlidingWindow]`) for the breakdown feature.

### 6.4 Baseline (R3)

**Approach: EWMA mean and EWMA variance, with a warm-up period and freeze-on-anomaly.**

```
Warm-up:  collect first N samples (BASELINE_WARMUP_SAMPLES), compute plain mean/std, seed the EWMA.
Update:   diff = x - mean
          mean = mean + alpha * diff
          var  = (1 - alpha) * (var + alpha * diff * diff)
          std  = max(sqrt(var), BASELINE_MIN_STD)
Freeze:   if an alert is OPEN (or the current sample is a breach), DO NOT update.
          Otherwise the anomaly poisons the baseline and the detector "learns" the outage as normal.
```

Rules:
- Skip samples where `total < MIN_EVENTS_IN_WINDOW` (rate unreliable). These do not update the baseline and do not trigger the detector.
- Expose `Baseline.state()` returning `{mean, std, samples, ready, upper_band}` where `upper_band = mean + Z_LOW * std`. The frontend draws this.
- **Optional hardening:** also keep the last ~30 min of samples and use median/MAD as a robust alternative, selectable with `BASELINE_METHOD=ewma|mad`.
- Persist the baseline to `data/baseline.json` every minute and reload on startup (skips warm-up after a restart).

### 6.5 Detector (R4) and Severity (R5)

Per evaluation tick, with `rate = window.error_rate`, `z = (rate - mean) / std`:

```python
# severity.py
from enum import IntEnum

class Severity(IntEnum):
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

def classify(z: float, rate: float, cfg) -> Severity:
    if rate < cfg.MIN_ABS_RATE:            # absolute floor: ignore tiny rates
        return Severity.NONE
    if rate >= cfg.ABS_RATE_CRITICAL or z >= cfg.Z_CRITICAL: return Severity.CRITICAL
    if z >= cfg.Z_HIGH:    return Severity.HIGH
    if z >= cfg.Z_MEDIUM:  return Severity.MEDIUM
    if z >= cfg.Z_LOW:     return Severity.LOW
    return Severity.NONE
```

Severity meaning (shown in UI and in alert messages):
| Severity | Trigger | Color | Action |
|---|---|---|---|
| LOW | z ≥ 3 | yellow | Dashboard only |
| MEDIUM | z ≥ 4.5 | orange | + SNS notification |
| HIGH | z ≥ 6.5 | red | + SNS notification |
| CRITICAL | z ≥ 9 or rate ≥ 50% | dark red, pulsing | + SNS notification, top of feed |

**Detector output per tick:** `DetectionResult{ts, rate, z, severity, breaching: bool, baseline_mean, baseline_std, window_total, window_errors}`.

**Secondary detector (optional, same structure):** *throughput anomaly* on `events_per_sec` using its own EWMA baseline and two-sided z-score (a drop to near zero means the service is dead; a spike may mean a flood). Emits `type=THROUGHPUT_DROP|THROUGHPUT_SPIKE`.

### 6.6 Alert Manager (lifecycle, dedupe, flap protection)

State machine per `alert_key` (e.g. `error_rate:global`, `error_rate:service=payments`):

```
          confirm_ticks breaches               severity increases
   IDLE ───────────────────────► OPEN ───────────────────────────► ESCALATED (still OPEN, new event)
     ▲                             │                                   │
     │    resolve_ticks calm       │                                   │
     └──────────── RESOLVED ◄──────┴───────────────────────────────────┘
        (cooldown before re-open)
```

Emit an **alert event** (to the bus and the publisher queue) on:
1. `OPENED`: first confirmed breach
2. `ESCALATED`: severity goes up (no event for a downgrade, but update the live alert's `current_severity`)
3. `RESOLVED`: calm for `RESOLVE_TICKS` (include duration and peak severity)

Never emit repeated events while severity is unchanged, so the CloudWatch and SNS streams stay clean.

**Alert model:**
```python
class Alert(BaseModel):
    id: str                 # uuid4
    key: str                # "error_rate:global"
    status: Literal["OPEN", "RESOLVED"]
    event: Literal["OPENED", "ESCALATED", "RESOLVED"]
    severity: str           # LOW|MEDIUM|HIGH|CRITICAL
    peak_severity: str
    title: str              # "Error rate spike: 34.2% (baseline 2.1%)"
    error_rate: float
    baseline_mean: float
    baseline_std: float
    z_score: float
    window_seconds: int
    window_total: int
    window_errors: int
    top_errors: list[dict]  # [{"message": "...", "count": 42, "service": "payments"}]
    opened_at: str
    updated_at: str
    resolved_at: str | None
    acknowledged: bool = False
    acknowledged_by: str | None = None
```

`top_errors`: while processing lines, maintain a `Counter` of normalized error messages in the window (replace digits, UUIDs and IPs with placeholders). Attach the top 3 to each alert. This is the "why" that makes the alert useful.

### 6.7 Evaluator loop (pseudocode)

```python
async def evaluator_loop():
    while True:
        await asyncio.sleep(cfg.EVAL_INTERVAL_SEC)
        snap = window.snapshot()
        reliable = snap["total"] >= cfg.MIN_EVENTS_IN_WINDOW

        if reliable and not baseline.ready:
            baseline.warmup_add(snap["error_rate"])
        result = detector.evaluate(snap, baseline) if (reliable and baseline.ready) else None

        breaching = bool(result and result.severity > Severity.NONE)
        if reliable and baseline.ready and not (breaching or alert_manager.has_open_alert()):
            baseline.update(snap["error_rate"])          # freeze during anomalies

        bus.publish("metric", metric_point(snap, baseline, result))
        bus.publish("baseline", baseline.state())         # or bundle it with the metric
        for ev in alert_manager.process(result):          # returns 0..n alert events
            bus.publish("alert", ev)
            dispatcher.enqueue(ev)
```

---

## 7. Backend API Contract

### REST (also the polling fallback)
| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | `{status, uptime, tailing: bool, baseline_ready, ws_clients, publish_mode}` |
| GET | `/api/config` | Non-secret thresholds (frontend uses them for chart reference lines) |
| GET | `/api/metrics?minutes=30` | Recent `MetricPoint[]` for chart hydration |
| GET | `/api/alerts?status=&limit=50` | Alert history, newest first |
| GET | `/api/alerts/active` | Currently OPEN alerts |
| POST | `/api/alerts/{id}/ack` | Body `{by}`, marks acknowledged |
| GET | `/api/poll?since_seq=N` | **Polling fallback**: all envelopes with `seq > N` (max 500) plus `latest_seq` |
| GET | `/api/logs/recent?limit=100` | Last N parsed log lines |
| POST | `/api/sim/spike` | Body `{duration_sec, error_ratio}` triggers a simulated anomaly (demo only, guarded by `ENABLE_SIM=true`) |
| POST | `/api/sim/recover` | Ends the simulated anomaly |

### WebSocket `/ws`
- On connect, server sends `{"type":"snapshot","data":{"metrics":[...last 5 min],"active_alerts":[...],"baseline":{...},"config":{...}}}`
- Then streams envelopes: `metric` (every eval tick), `alert` (on lifecycle events), `log` (sampled, max ~10/sec, error lines prioritized), `heartbeat` (every 15 s)
- Client may send `{"type":"ping"}` and the server replies `{"type":"pong"}`
- Handle disconnects cleanly (remove from the client set, no exceptions leaking)
- **Backpressure:** each client gets a bounded `asyncio.Queue(maxsize=200)`. If it's full, drop the oldest `log` messages first, never drop `alert` messages.

### Event Bus (`bus.py`)
- `publish(type, data)` assigns `seq`, appends to a `deque(maxlen=RING_BUFFER_SIZE)`, and pushes to all subscriber queues
- `since(seq)` returns the buffered items after `seq` (powers `/api/poll`)
- Keep alerts in a separate, longer-lived list (`alert_store`) so they aren't evicted by high-volume metrics

---

## 8. AWS Integration (R8)

### 8.1 Resources
- **CloudWatch Log Group:** `/hackathon/log-anomaly-detector`, stream `alerts`
- **SNS Topic:** `log-anomaly-alerts`, plus an email subscription (confirm it via the emailed link *before* the demo)
- *(Optional)* CloudWatch **custom metric** `LogAnomaly/ErrorRate` and an alarm on it

`infra/aws-setup.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
REGION=${AWS_REGION:-ap-south-1}
LG=/hackathon/log-anomaly-detector
aws logs create-log-group --log-group-name "$LG" --region $REGION || true
aws logs put-retention-policy --log-group-name "$LG" --retention-in-days 7 --region $REGION
aws logs create-log-stream --log-group-name "$LG" --log-stream-name alerts --region $REGION || true
ARN=$(aws sns create-topic --name log-anomaly-alerts --region $REGION --query TopicArn --output text)
aws sns subscribe --topic-arn "$ARN" --protocol email --notification-endpoint "$ALERT_EMAIL" --region $REGION
echo "SNS_TOPIC_ARN=$ARN"
```

`infra/iam-policy.json` (least privilege):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow",
      "Action": ["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents","logs:DescribeLogStreams"],
      "Resource": "arn:aws:logs:*:*:log-group:/hackathon/log-anomaly-detector*" },
    { "Effect": "Allow",
      "Action": ["sns:Publish"],
      "Resource": "arn:aws:sns:*:*:log-anomaly-alerts" },
    { "Effect": "Allow",
      "Action": ["cloudwatch:PutMetricData"],
      "Resource": "*",
      "Condition": {"StringEquals": {"cloudwatch:namespace": "LogAnomaly"}} }
  ]
}
```
Credentials: use the standard boto3 chain (env vars `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`, `~/.aws`, or an IAM role). **Never hardcode or commit keys.** `.env` goes in `.gitignore`.

### 8.2 Publisher design
```python
class Publisher(Protocol):
    async def publish(self, alert: Alert) -> None: ...
```
- `ConsolePublisher`: dry-run, pretty-prints JSON (default so the project runs with no AWS account)
- `CloudWatchPublisher`
  - On startup: ensure the group and stream exist (catch `ResourceAlreadyExistsException`)
  - `put_log_events` with a **single JSON message per alert** (structured logs are queryable with Logs Insights), timestamp in ms
  - Sequence tokens are no longer required, so don't over-engineer them
- `SnsPublisher`
  - `sns.publish(TopicArn, Subject="[HIGH] Error rate spike: 34%", Message=<human-readable text + JSON>, MessageAttributes={"severity": {...}, "alert_key": {...}, "event": {...}})`
  - Subject max 100 chars, ASCII only
  - Only publish if `severity >= SNS_MIN_SEVERITY` and for events OPENED, ESCALATED and RESOLVED (RESOLVED optional)
- `Dispatcher`
  - `asyncio.Queue` of alert events, worker calls each publisher via `asyncio.to_thread` (boto3 is sync)
  - **Retry with exponential backoff** (3 attempts: 1 s, 2 s, 4 s) on throttling and network errors
  - A failed publisher must **never** crash the pipeline or block the UI. Log the error, increment `publish_failures`, and surface it in `/api/health`
  - Each alert gets a `publish_status` field (`{cloudwatch: "ok|failed|skipped", sns: "..."}`) shown as small icons in the UI

**CloudWatch Logs message shape:**
```json
{"service":"log-anomaly-detector","event":"OPENED","severity":"HIGH","alert_id":"…","title":"Error rate spike: 34.2% (baseline 2.1%)","error_rate":0.342,"baseline_mean":0.021,"z_score":7.4,"window_seconds":60,"top_errors":[{"message":"DB connection timeout","count":112}]}
```
Handy Logs Insights query for the demo:
```
fields @timestamp, severity, title, error_rate | filter severity in ["HIGH","CRITICAL"] | sort @timestamp desc
```

### 8.3 Local/offline testing of AWS code
- **Unit tests:** `moto` (`@mock_aws`) for logs and SNS
- **Optional:** LocalStack in Docker Compose with `AWS_ENDPOINT_URL=http://localstack:4566`
- `PUBLISH_MODE=dry_run` for anything with no AWS at all

---

## 9. Log Simulator (`backend/simulator/generate_logs.py`)

Critical for testing and the demo. A CLI that appends realistic lines to `LOG_FILE_PATH`.

```
python -m simulator.generate_logs --file ./data/app.log --rps 30 --base-error 0.02
python -m simulator.generate_logs ... --scenario spike --at 120 --duration 60 --error-ratio 0.35
```

- Traffic: Poisson-like arrivals around `--rps`, jittered with a small sine wave (fake daily pattern)
- Services: `auth, payments, orders, search, gateway` with different weights and per-service error propensity
- Realistic message templates for INFO, WARNING and ERROR (e.g. `"DB connection timeout"`, `"Upstream 502 from inventory"`, `"NullPointerException in OrderService"`)
- Scenarios: `spike` (error ratio jumps), `ramp` (gradually increasing), `flood` (volume x10), `outage` (only errors, then silence), `flapping`
- Flush after each batch so the tailer sees writes immediately
- Also runnable in-process: `/api/sim/spike` toggles a shared flag file or control file (`data/sim_control.json`) that the generator polls. This lets the **UI button** trigger anomalies live.

---

## 10. Frontend Plan (React + Vite + TS + Tailwind + Recharts)

### 10.1 `useLiveFeed` hook, the heart of the frontend
```
State: metrics[], alerts[], activeAlerts[], baseline, logs[], connection: "live"|"reconnecting"|"polling"|"offline"

1. Fetch /api/config, /api/metrics, /api/alerts (hydrate)
2. Open WebSocket to ws://<host>/ws
   - onmessage: dispatch by envelope.type; dedupe by seq (ignore seq <= lastSeq)
   - onclose/onerror: exponential backoff reconnect (1s, 2s, 4s, max 15s), connection = "reconnecting"
3. After 3 failed reconnects → fall back to polling GET /api/poll?since_seq=lastSeq every 2s, connection = "polling"
   - keep trying WS in the background; switch back to "live" once it connects
4. Cap in-memory arrays (metrics: last 720 points; logs: last 200; alerts: last 200)
```

### 10.2 Layout (single page, dark theme default)
```
┌──────────────────────────────────────────────────────────────────────────┐
│ Log Anomaly Detector           ● LIVE (WebSocket)        [Simulate ▾]    │
├──────────────┬──────────────┬──────────────┬─────────────────────────────┤
│ Error rate   │ Baseline     │ Z-score      │ Active alerts               │
│ 2.3%         │ 2.0% ± 0.6   │ 0.5          │ 0                           │
├──────────────┴──────────────┴──────────────┴─────────────────────────────┤
│  Error Rate (60s window)                    ┌──────────────────────────┐ │
│  [line chart + shaded baseline band         │  ALERT FEED (live)       │ │
│   + red shaded regions where alerts open]   │  🔴 CRITICAL 10:15:20    │ │
│                                             │  Error rate 61% ...      │ │
│                                             │  top: DB timeout ×212    │ │
│                                             │  ☁ CW ✓  ✉ SNS ✓  [Ack]  │ │
│                                             │  🟠 MEDIUM 10:14:55 ...  │ │
├─────────────────────────────────────────────┴──────────────────────────┤
│  Live log tail (errors in red, auto-scroll, pause button)               │
└──────────────────────────────────────────────────────────────────────────┘
```

### 10.3 Component specs
- **Header:** connection pill (green live / amber reconnecting / blue polling / red offline), simulate dropdown (calls `/api/sim/spike`, only visible if the config says `sim_enabled`)
- **KpiCards:** current error rate (colored by severity), baseline mean ± std (shows "Learning… 12/24" during warm-up), latest z-score, count of active alerts, events/sec
- **ErrorRateChart:**
  - Recharts `ComposedChart`: `Line` for rate, `Area` for the baseline band (`mean - Z_LOW*std` to `mean + Z_LOW*std`, stacked-area trick), `ReferenceArea` for intervals where an alert was open (color by peak severity), `ReferenceLine` for the `MIN_ABS_RATE`
  - X axis is time (HH:mm:ss), Y axis is 0–100% (auto-scaled with a min of 10%), tooltip shows the rate, baseline, z and total events
  - Disable animation for smooth live updates (`isAnimationActive={false}`)
- **AlertFeed:** newest first, animated slide-in for new items, severity badge and color, title, timestamp (relative, "12s ago"), z-score, top errors, status chip (OPEN or RESOLVED with duration), publish-status icons, ack button, filter chips by severity
- **AlertToast:** toast on new MEDIUM+ alerts (auto-dismiss 6 s, CRITICAL stays until dismissed). Optional short beep, off by default.
- **LogTail:** monospace list, auto-scroll with a pause toggle, ERROR lines red, WARNING amber, click a service name to filter

### 10.4 Types (`types.ts`) mirror the backend Pydantic models exactly
`Envelope`, `MetricPoint{ts, error_rate, total, errors, events_per_sec, baseline_mean, baseline_std, upper_band, z, severity}`, `Alert`, `LogLine`, `Baseline`, `AppConfig`.

Vite dev proxy: `/api` and `/ws` → `http://localhost:8000`.

---

## 11. Docker & Run Instructions

`docker-compose.yml` services:
- `backend`: FastAPI, mounts `./data:/app/data`, env from `.env`, port 8000
- `simulator`: same image, command `python -m simulator.generate_logs ...`, mounts `./data`
- `frontend`: Vite build served by nginx (port 5173 mapped)
- `localstack` (profile `aws-local`): `localstack/localstack`, port 4566, services `logs,sns`

`Makefile` targets: `make dev` (uvicorn + vite locally), `make up` (compose), `make test`, `make sim-spike`, `make aws-setup`.

`README.md` must include: a 5-line quick start, the architecture diagram, the config table, a demo script, and troubleshooting.

---

## 12. Testing Strategy

| Test | What it verifies |
|---|---|
| `test_parser` | Text and JSON parsing, malformed lines, level normalization, missing timestamps |
| `test_window` | Bucket eviction at boundaries, correct rate math, empty-window safety |
| `test_baseline` | Warm-up gating, EWMA convergence, freeze behavior, std floor |
| `test_detector` | Severity boundaries (z just below and above each threshold), the absolute-rate floor, the reliability gate |
| `test_alerts` | Confirm ticks, escalation emits once, resolve after calm ticks, cooldown blocks re-open, no duplicate events |
| `test_publishers` | moto-based CloudWatch and SNS calls, retry on throttle, failures don't propagate |
| `test_tailer` | Appended lines picked up, partial line buffering, truncation and rotation handling |
| `test_e2e` | Start the pipeline, feed synthetic lines with a fake clock, assert alert OPENED then RESOLVED, and WS clients receive them |

**Make time injectable** (pass `now` or a `Clock` object everywhere) so tests don't sleep.

Acceptance target: `pytest` fully green, and the E2E test runs in under 10 seconds.

---

## 13. Build Phases (with acceptance criteria)

> Suggested pacing for a 24-hour hackathon is in brackets. Adjust to your schedule.

### Phase 1: Skeleton & data pipeline [Hours 0–3]
**Tasks:** repo scaffold, config, models, parser, tailer, window, simulator (steady traffic only), `/api/health`.
**Accept when:** running the simulator and the backend prints a rolling error rate every 5 s that matches the `--base-error` setting within noise.

### Phase 2: Baseline + detection + alerts [Hours 3–7]
**Tasks:** baseline, detector, severity, alert manager, event bus, `/api/alerts`, `/api/metrics`, unit tests for all of them.
**Accept when:** simulator `--scenario spike` causes exactly one OPENED, correct severity escalation, then one RESOLVED after the spike, and the unit tests pass.

### Phase 3: Real-time API [Hours 7–9]
**Tasks:** WebSocket endpoint with snapshot, heartbeats and backpressure, `/api/poll`, CORS, sim endpoints.
**Accept when:** `wscat` or a test script receives metric and alert envelopes live, and `/api/poll?since_seq=` returns the same data.

### Phase 4: Frontend [Hours 9–16]
**Tasks:** Vite app, `useLiveFeed` (WS, reconnect, polling fallback), KpiCards, ErrorRateChart, AlertFeed, LogTail, toasts, SimControls.
**Accept when:** clicking "Simulate spike" shows the chart rising above the band, an alert card sliding in within about 10 s, and auto-resolving. Killing the backend shows "reconnecting", and restarting recovers without a page refresh.

### Phase 5: AWS publishing [Hours 16–19]
**Tasks:** publishers, dispatcher (retry and queue), `aws-setup.sh`, IAM policy, moto tests, publish-status shown in the UI.
**Accept when:** with `PUBLISH_MODE=aws`, an alert appears in the CloudWatch log stream and an email arrives from SNS. With AWS blocked or misconfigured, the app keeps running and the UI shows the failure.

### Phase 6: Polish & demo readiness [Hours 19–24]
**Tasks:** Docker Compose, README, `top_errors` panel, per-service breakdown (if time), dark mode, error states, 60-second demo script rehearsal, screenshots or GIF.
**Accept when:** `docker compose up` on a clean machine yields a working demo, and the demo script runs flawlessly twice in a row.

---

## 14. Demo Script (3 minutes)

1. **(0:00)** "Here's our live log stream and dashboard. Baseline learned: about 2% errors." Show the chart and the log tail.
2. **(0:30)** Click **Simulate → Spike (35% errors)**. Narrate the chart climbing.
3. **(0:45)** Alert card appears: **MEDIUM → HIGH**. Point out the z-score, the top error ("DB connection timeout ×212"), and the status icons.
4. **(1:15)** Switch to the AWS Console: CloudWatch Logs shows the structured alert, and the SNS email arrives on the phone.
5. **(1:45)** Click **Recover**. The alert auto-resolves with its duration, and the baseline was not poisoned (baseline stays about 2%).
6. **(2:15)** Kill the backend to show the resilience: UI goes "reconnecting", then recovers.
7. **(2:40)** Wrap-up: architecture slide with the algorithm summary (sliding window, EWMA baseline, z-score, hysteresis).

---

## 15. Edge Cases & Design Decisions (agent must handle these)

- **Cold start:** no detection during warm-up. UI shows learning progress.
- **Low traffic:** below `MIN_EVENTS_IN_WINDOW`, skip the sample (avoids 1/2 = 50% false alarms).
- **Zero-variance baseline:** std floor (`BASELINE_MIN_STD`) prevents division by ~0 and infinite z-scores.
- **Baseline poisoning:** freeze updates during anomalies (described in 6.4).
- **Flapping:** confirm ticks, resolve ticks, and cooldown together give hysteresis.
- **Log rotation/truncation:** handled in the tailer.
- **Burst of logs:** bounded queue and batch reads. Never block the event loop on file IO.
- **AWS down or throttled:** async queue, retry with backoff, non-fatal failures, visible status.
- **Slow WebSocket clients:** bounded per-client queues, drop `log` before `alert`.
- **Clock/timezone:** use UTC everywhere, ISO-8601 with `Z`.
- **Security:** no secrets in the repo, CORS restricted to configured origins, sim endpoints disabled unless `ENABLE_SIM=true`.
- **Idempotent restarts:** reload the persisted baseline, and the tailer starts at EOF so old lines aren't replayed.

---

## 16. Definition of Done Checklist

- [ ] Tails a live-growing file, survives rotation and truncation
- [ ] Rolling 60 s error rate via bucketed sliding window
- [ ] Baseline with warm-up, EWMA and freeze-on-anomaly
- [ ] Z-score detection with the absolute-rate floor and reliability gate
- [ ] 4 severity levels with documented thresholds
- [ ] Alert lifecycle (OPENED, ESCALATED, RESOLVED) with dedupe and cooldown
- [ ] WebSocket streaming with polling fallback and auto-reconnect
- [ ] React dashboard: KPIs, chart with baseline band, alert feed, log tail, toasts
- [ ] CloudWatch Logs and SNS publishing with retry, plus a dry-run mode
- [ ] Simulator with spike, ramp, flood and outage scenarios and UI trigger
- [ ] Unit and E2E tests passing
- [ ] Docker Compose, README, IAM policy, AWS setup script
- [ ] Rehearsed demo script

---

## 17. Instructions for the Coding Agent

1. Read this whole document first. Then create the repository structure from section 4.
2. Work **phase by phase** (section 13). After each phase, run the tests, verify the acceptance criteria, and summarize what you did before continuing.
3. Write tests alongside code, not at the end. Make time injectable.
4. Type everything (Pydantic models in Python, TypeScript types in the frontend). Keep the two in sync.
5. Default to `PUBLISH_MODE=dry_run` so the project runs without AWS credentials. Never hardcode secrets.
6. Prefer simple and robust over clever. This must work live on stage.
7. Keep files small and focused as laid out above. Add docstrings explaining the *why* for the baseline and detector logic.
8. When done, produce the README with a quick start and finish by running the full demo script yourself (via the simulator) to verify it end to end.
