---
title: Log Watch
emoji: 📈
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Real-time log anomaly detection with live alerts
---

# Log Watch: live demo

Real-time log anomaly detection. This Space runs the full stack in one container:
- a traffic generator writing realistic logs (about 2% errors);
- the detector (median/MAD baseline, 5-minute + 60-second windows, severity levels);
- the live dashboard, streamed over WebSocket.

**Try it:** give the baseline about 2 minutes to learn, then click **Inject incident** and watch the alert appear.

Alerts are published in `dry_run` mode here (no AWS account attached). All visitors share one simulated service, so an incident injected by someone else shows up for you too.

Source code, benchmark and docs: https://github.com/pronov06/log-watch
