# Log Watch on Hugging Face Spaces: one container runs the log generator, the detector
# backend and the dashboard, all on the Space's port 7860.

# --- Build the dashboard ---
FROM node:20-alpine AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Runtime ---
FROM python:3.12-slim

# Spaces run containers as uid 1000
RUN useradd -m -u 1000 user
WORKDIR /app

# Runtime dependencies only (the repo's requirements.txt also carries test tooling)
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" pydantic pydantic-settings boto3 python-dotenv

COPY backend/app ./app
COPY backend/simulator ./simulator
COPY --from=ui /ui/dist ./static
COPY start.sh ./start.sh

RUN mkdir -p /app/data && chown -R user:user /app
USER user

ENV PYTHONUNBUFFERED=1 \
    LOG_FILE_PATH=/app/data/app.log \
    BASELINE_PATH=/app/data/baseline.json \
    STATIC_DIR=/app/static \
    PUBLISH_MODE=dry_run \
    ENABLE_SIM=true \
    LOG_JSON=true

EXPOSE 7860
CMD ["bash", "start.sh"]
