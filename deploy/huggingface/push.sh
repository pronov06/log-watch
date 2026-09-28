#!/usr/bin/env bash
# Build the dashboard, assemble the Hugging Face Space (free Gradio SDK) and push it.
#
#   bash deploy/huggingface/push.sh <hf-user>/<space-name>      e.g.  pronov06/log-watch
#
# Prerequisites: a Space created at https://huggingface.co/new-space with the **Gradio** SDK
# (Blank template), and a Hugging Face access token with write permission
# (git asks for it as the password).
set -euo pipefail

SPACE="${1:?usage: push.sh <hf-user>/<space-name>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$ROOT/deploy/huggingface"
OUT="$(mktemp -d)"

echo "Building the dashboard"
(cd "$ROOT/frontend" && npm run build)

echo "Assembling Space in $OUT"
mkdir -p "$OUT/backend"
cp -r "$ROOT/backend/app" "$ROOT/backend/simulator" "$OUT/backend/"
cp -r "$ROOT/frontend/dist" "$OUT/static"
cp "$HERE/space.py" "$HERE/requirements.txt" "$HERE/README.md" "$OUT/"
find "$OUT" -name "__pycache__" -type d -prune -exec rm -r {} +

cd "$OUT"
git init -q -b main
git add -A
git -c user.name=pronov06 -c user.email=mazumdarpronov@gmail.com commit -qm "Deploy Log Watch"
git push --force "https://huggingface.co/spaces/$SPACE" main

echo
echo "Pushed. The Space builds in a few minutes: https://huggingface.co/spaces/$SPACE"
