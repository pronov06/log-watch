"""
Log line parser — supports both text and JSON formats.

Auto-detection: if the line starts with '{', try JSON first, otherwise use the text regex.
Malformed lines are counted (parse_failures) and returned as None, never raised.
Level normalization: WARN → WARNING, FATAL/CRITICAL → ERROR.

Uses **processing time** for bucketing (simple and robust). The original event
timestamp is preserved in the LogEvent for display purposes.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Literal

from app.models import LogEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Level normalization
# ---------------------------------------------------------------------------

_LEVEL_MAP: dict[str, str] = {
    "TRACE": "DEBUG",
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARN": "WARNING",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "FATAL": "ERROR",
    "CRITICAL": "ERROR",
    "SEVERE": "ERROR",
}

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


def _normalize_level(raw: str) -> str:
    """Map any log level string to one of DEBUG, INFO, WARNING, ERROR."""
    return _LEVEL_MAP.get(raw.upper().strip(), "INFO")


# ---------------------------------------------------------------------------
# Text format regex
# ---------------------------------------------------------------------------

# Matches lines like:
# 2026-09-28T10:15:03.412Z ERROR service=payments msg="DB connection timeout" latency_ms=5021
# 2026-09-28T10:15:03.500Z INFO  service=auth msg="login ok"
_TEXT_PATTERN = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[\.\d]*Z?)\s+"
    r"(?P<level>[A-Z]+)\s+"
    r"(?:service=(?P<service>\S+)\s+)?"
    r"(?:msg=\"(?P<msg>[^\"]*)\"|msg=(?P<msg2>\S+))?"
    r"(?P<rest>.*)",
    re.IGNORECASE,
)

# Fallback: just level + message
_SIMPLE_PATTERN = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[\.\d]*Z?)\s+"
    r"(?P<level>[A-Z]+)\s+"
    r"(?P<msg>.*)",
    re.IGNORECASE,
)


def _parse_timestamp(raw: str) -> datetime:
    """Best-effort ISO-8601 timestamp parsing, falls back to now()."""
    try:
        # Handle common variants
        clean = raw.strip().rstrip("Z")
        if "T" in clean:
            return datetime.fromisoformat(clean).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(clean).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Parse functions
# ---------------------------------------------------------------------------

def _parse_json(line: str) -> LogEvent | None:
    """Attempt to parse a JSON log line."""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None

    ts_raw = obj.get("ts") or obj.get("timestamp") or obj.get("time") or ""
    ts = _parse_timestamp(ts_raw) if ts_raw else datetime.now(timezone.utc)

    level_raw = obj.get("level") or obj.get("severity") or "INFO"
    level = _normalize_level(str(level_raw))

    service = obj.get("service") or obj.get("source") or "unknown"
    message = obj.get("msg") or obj.get("message") or obj.get("text") or ""

    return LogEvent(ts=ts, level=level, service=str(service), message=str(message), raw=line)


def _parse_text(line: str) -> LogEvent | None:
    """Attempt to parse a text-format log line."""
    m = _TEXT_PATTERN.match(line)
    if m:
        ts = _parse_timestamp(m.group("ts"))
        level = _normalize_level(m.group("level"))
        service = m.group("service") or "unknown"
        message = m.group("msg") or m.group("msg2") or m.group("rest") or ""
        return LogEvent(ts=ts, level=level, service=service, message=message.strip(), raw=line)

    m = _SIMPLE_PATTERN.match(line)
    if m:
        ts = _parse_timestamp(m.group("ts"))
        level = _normalize_level(m.group("level"))
        message = m.group("msg") or ""
        return LogEvent(ts=ts, level=level, service="unknown", message=message.strip(), raw=line)

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Track parse failures for observability
parse_failures: int = 0


def parse_line(
    line: str,
    fmt: Literal["auto", "text", "json"] = "auto",
) -> LogEvent | None:
    """
    Parse a single log line into a LogEvent.

    - `auto`: if the line starts with `{`, try JSON first, then text.
    - `json`: JSON only.
    - `text`: text regex only.

    Returns None for malformed lines (increments parse_failures counter).
    """
    global parse_failures

    line = line.strip()
    if not line:
        return None

    event: LogEvent | None = None

    if fmt == "json":
        event = _parse_json(line)
    elif fmt == "text":
        event = _parse_text(line)
    else:  # auto
        if line.startswith("{"):
            event = _parse_json(line)
            if event is None:
                event = _parse_text(line)
        else:
            event = _parse_text(line)
            if event is None:
                event = _parse_json(line)

    if event is None:
        parse_failures += 1
        logger.debug("Failed to parse line: %s", line[:120])

    return event
