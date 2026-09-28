# STATE  (iteration 0 → Phase 0 done, updated 2026-09-28)

## Facts
- Branch feat/realtime (baseline commit 9051bce on master). Commit cmd: `git -c user.name=raktimchandra69 -c user.email=raktimchandra69@gmail.com -c core.autocrlf=false commit`. `.gitattributes` forces LF.
- Tools: Python 3.14.7, Node 24, frontend/node_modules present. NO docker, NO aws CLI in PATH (bash).
- G1: `cd backend && python -m pytest -q -p no:cacheprovider` → 70 passed baseline. G2: `cd frontend && npm run build` OK (chunk-size warning only).
- Backend CWD = backend/; relative paths `./data/...` resolve to backend/data (baseline.json, sim_control.json). Makefile dev-sim writes ../data/app.log but sim reads control from ../data/sim_control.json while API writes backend/data/sim_control.json → MISMATCH in local dev (docker OK: both /app/data).
- Ports: backend 8000, vite 5173 (proxies /api, /ws → 127.0.0.1:8000). Docker frontend nginx on 5173.
- Plan line ranges: §1 15-46, §6 241-451, §7 452-481, §8 482-558, §10 577-629, §13 663-692, §15 705-721, §16 722-738.
- File map: tailer(single file, text-mode read) parser(text+json only) window(1s buckets) baseline(EWMA, persist ./data/baseline.json hardcoded) detector(classify_severity; no severity.py — OK) alerts(AlertManager IDLE/OPEN/COOLDOWN) pipeline(consumer+evaluator loops) bus(ring+alert_store, seq) api/routes api/ws publishers/{console,cloudwatch,sns,dispatcher}.

## Requirement matrix
| ID | Status | Evidence | Next action |
|---|---|---|---|
| R1 tail | PARTIAL | test_tailer (append/partial/truncate) | text-mode seek/tell offsets wrong w/ CRLF/UTF-8; no rotation test |
| R2 window | PASS | test_window.py | - |
| R3 baseline | PARTIAL | test_baseline.py | persist path hardcoded (test pollution); UI never gets live baseline/warmup fields |
| R4 detect | PASS | test_detector.py, test_e2e | - |
| R5 severity | PASS | detector.classify_severity + tests | - |
| R6 realtime FE | FAIL | useLiveFeed.ts | polling reads `items` (backend `envelopes`); seq reset after backend restart freezes UI |
| R7 alerts shown | PARTIAL | AlertFeed | ack not broadcast; publish_status never reaches UI |
| R8 AWS push | PARTIAL | moto tests | dispatcher retry dead (publishers swallow errors); status not surfaced |
| DoD sim scenarios | FAIL | sim ignores UI scenario (ramp/flood/outage → spike); outage/flood not real | control file carries scenario |
| DoD lifecycle/dedupe | PASS | test_alerts.py | - |
| RT1 sources/formats | TODO | - | globs, multi-file, pylogging/nginx/syslog |
| RT2 latency | TODO | - | ingest lag + detect latency in health/UI |
| RT3 AWS | TODO | - | CW batching, metrics, jitter, CFN alarm |
| RT4 robustness | TODO | - | ready endpoint, flush, JSON logs, validation |
| RT5 FE UX | PARTIAL | Header conn state | last-event age, latency, warmup, ack broadcast |
| RT6 security | PARTIAL | .env ignored | non-root containers, IAM check |
| RT7 ops | PARTIAL | compose exists | healthchecks, log mount, README |
| RT8 tests | TODO | - | parser formats, smoke script |

## Queue
1. P0 FE feed: polling key + server-restart seq reset (boot_id) + handle `baseline` envelopes
2. P0 Dispatcher: real retry (publishers raise), publish_status → bus update event
3. P0 Tailer binary offsets + rotation test; baseline persist path config (BASELINE_PATH)
4. P1 Baseline warmup fields + config publish_mode/min_events; ack broadcast
5. P1 Sim scenarios via control file (ramp/flood/outage real); unify control path
6. P2 RT1 multi-source + formats + tests
7. P2 RT2 latency metrics + UI indicator
8. P2 RT3 CW batching + metrics publisher + jitter + CFN alarm + IAM
9. P2 RT4 ready/flush/JSON logging/validation
10. P2 RT6/RT7 Docker non-root, healthchecks, log mount; README
11. P2 G4 smoke script; G5 browser check

## Attempts
(none)

## Gate results
- run0 (baseline): G1 PASS(70) G2 PASS G3 FAIL G4 n/a G5 n/a G6 BLOCKED-ENV(no docker) G7 PASS

## Log
- iter0: Phase 0 audit; .gitignore fixed (**/data, .pytest_cache), .gitattributes, baseline commit, branch.
