FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY simulator ./simulator

# Unprivileged runtime user. /app/data holds the tailed demo log, the persisted
# baseline and the simulator control file; it is a named volume in compose, which
# inherits this ownership on first use.
RUN useradd --system --uid 10001 --home /app app \
    && mkdir -p /app/data && chown -R app:app /app/data
USER app

EXPOSE 8000

# Ready (not just alive): pipeline running and at least one source being tailed
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/ready || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "10"]
