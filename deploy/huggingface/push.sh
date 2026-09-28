#!/usr/bin/env bash
# Assemble the Hugging Face Space from this repo and push it.
#
#   bash deploy/huggingface/push.sh <hf-user>/<space-name>      e.g.  pronov06/log-watch
#
# Prerequisites: a Docker Space created at https://huggingface.co/new-space, and a
# Hugging Face access token with write permission (git asks for it as the password).
set -euo pipefail

SPACE="${1:?usage: push.sh <hf-user>/<space-name>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$ROOT/deploy/huggingface"
OUT="$(mktemp -d)"

echo "Assembling Space in $OUT"
mkdir -p "$OUT/backend" "$OUT/frontend"
cp -r "$ROOT/backend/app" "$ROOT/backend/simulator" "$OUT/backend/"
(cd "$ROOT/frontend" && cp -r package.json package-lock.json index.html vite.config.ts tsconfig.json \
    tailwind.config.js postcss.config.js src "$OUT/frontend/")
cp "$HERE/Dockerfile" "$HERE/start.sh" "$HERE/README.md" "$OUT/"
find "$OUT" -name "__pycache__" -type d -prune -exec rm -r {} +

cd "$OUT"
git init -q -b main
git add -A
git commit -qm "Deploy Log Watch"
git push --force "https://huggingface.co/spaces/$SPACE" main

echo
echo "Pushed. The Space builds in a few minutes: https://huggingface.co/spaces/$SPACE"
