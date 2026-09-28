#!/usr/bin/env bash
# Start the traffic generator in the background, then the backend (which also serves the dashboard).
set -euo pipefail

python -m simulator.generate_logs --file "$LOG_FILE_PATH" --rps 25 --base-error 0.02 &

exec uvicorn app.main:app --host 0.0.0.0 --port 7860 --timeout-graceful-shutdown 10
