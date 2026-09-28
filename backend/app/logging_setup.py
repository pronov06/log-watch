"""
Logging for the detector's own process (not the logs it monitors).

LOG_JSON=true emits one JSON object per line on stdout, so the container's output can
go straight into CloudWatch Logs / Loki and be queried by field. Otherwise a compact
human format is used for local development.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

_STD_ATTRS = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Anything passed via `extra=` becomes a top-level field
        entry.update({k: v for k, v in vars(record).items() if k not in _STD_ATTRS})
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(json_logs: bool = False, level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s [%(name)s] %(message)s", datefmt="%H:%M:%S"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Route uvicorn's loggers through the same handler/format
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
