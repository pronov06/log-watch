"""
Log line parser — turns raw lines from real systems into LogEvents.

Supported formats (all auto-detected with `LOG_FORMAT=auto`):
- json    : structured app logs (`level`/`severity`/`log.level`, `msg`/`message`, `ts`/`@timestamp`)
- text    : `2026-09-28T10:15:03Z ERROR service=api msg="..."` and plain `<ts> <LEVEL> <msg>`
- python  : stdlib logging, `2026-09-28 10:15:03,412 ERROR app.db: msg`
            and `2026-09-28 10:15:03,412 - app.db - ERROR - msg`
- nginx   : nginx/apache combined & common access logs; 5xx → ERROR, 4xx → WARNING
- syslog  : RFC 5424 and RFC 3164; level from <PRI> when present, else message keywords

Malformed lines are counted (parse_failures) and returned as None, never raised.
Level normalization: WARN → WARNING, FATAL/CRITICAL → ERROR.

Uses **processing time** for bucketing (simple and robust). The original event
timestamp is preserved in the LogEvent for display and ingest-lag measurement.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Callable, Literal

from app.models import LogEvent

logger = logging.getLogger(__name__)

LogFormat = Literal["auto", "text", "json", "python", "nginx", "syslog"]

# ---------------------------------------------------------------------------
# Level normalization
# ---------------------------------------------------------------------------

_LEVEL_MAP: dict[str, str] = {
    "TRACE": "DEBUG",
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "NOTICE": "INFO",
    "WARN": "WARNING",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "ERR": "ERROR",
    "FATAL": "ERROR",
    "CRITICAL": "ERROR",
    "CRIT": "ERROR",
    "SEVERE": "ERROR",
    "ALERT": "ERROR",
    "EMERG": "ERROR",
    "PANIC": "ERROR",
}


def _normalize_level(raw: str) -> str:
    """Map any log level string to one of DEBUG, INFO, WARNING, ERROR."""
    return _LEVEL_MAP.get(raw.upper().strip(), "INFO")


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

_TS = r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"


def _parse_timestamp(raw: str) -> datetime:
    """ISO-8601-ish → aware UTC datetime. Naive stamps are assumed UTC; falls back to now()."""
    try:
        clean = raw.strip().replace(",", ".")
        if clean.endswith("Z"):
            clean = clean[:-1] + "+00:00"
        dt = datetime.fromisoformat(clean)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _parse_strptime(raw: str, fmt: str) -> datetime:
    try:
        dt = datetime.strptime(raw, fmt)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

def _parse_json(line: str) -> LogEvent | None:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None

    ts_raw = obj.get("ts") or obj.get("timestamp") or obj.get("@timestamp") or obj.get("time") or ""
    ts = _parse_timestamp(str(ts_raw)) if ts_raw else datetime.now(timezone.utc)

    nested_log = obj.get("log") if isinstance(obj.get("log"), dict) else {}
    level_raw = (obj.get("level") or obj.get("severity") or obj.get("lvl")
                 or obj.get("levelname") or nested_log.get("level") or "INFO")
    level = _normalize_level(str(level_raw))

    service = obj.get("service") or obj.get("source") or obj.get("logger") or obj.get("name") or "unknown"
    if isinstance(service, dict):  # ECS: {"service": {"name": ...}}
        service = service.get("name", "unknown")
    message = obj.get("msg") or obj.get("message") or obj.get("text") or ""

    return LogEvent(ts=ts, level=level, service=str(service), message=str(message), raw=line)


# ---------------------------------------------------------------------------
# Text / Python logging
# ---------------------------------------------------------------------------

# 2026-09-28T10:15:03.412Z ERROR service=payments msg="DB connection timeout" latency_ms=5021
_TEXT_PATTERN = re.compile(
    rf"^(?P<ts>{_TS})\s+"
    r"(?P<level>[A-Z]+)\s+"
    r"service=(?P<service>\S+)\s*"
    r"(?:msg=\"(?P<msg>[^\"]*)\"|msg=(?P<msg2>\S+))?"
    r"(?P<rest>.*)",
    re.IGNORECASE,
)

# 2026-09-28 10:15:03,412 - app.db - ERROR - message   (common logging.Formatter layout)
_PY_DASH_PATTERN = re.compile(
    rf"^(?P<ts>{_TS})\s+-\s+(?P<name>\S+)\s+-\s+(?P<level>[A-Za-z]+)\s+-\s+(?P<msg>.*)$"
)

# 2026-09-28 10:15:03,412 ERROR app.db: message   /   <ts> [ERROR] message   /   <ts> ERROR message
_SIMPLE_PATTERN = re.compile(
    rf"^(?P<ts>{_TS})\s+\[?(?P<level>[A-Za-z]+)\]?\s+"
    r"(?:(?P<name>[\w.\-]+):\s+)?"
    r"(?P<msg>.*)$",
)


def _parse_text(line: str) -> LogEvent | None:
    m = _TEXT_PATTERN.match(line)
    if m:
        message = m.group("msg") or m.group("msg2") or m.group("rest") or ""
        return LogEvent(ts=_parse_timestamp(m.group("ts")), level=_normalize_level(m.group("level")),
                        service=m.group("service"), message=message.strip(), raw=line)

    m = _PY_DASH_PATTERN.match(line) or _SIMPLE_PATTERN.match(line)
    if m and m.group("level").upper() in _LEVEL_MAP:
        return LogEvent(ts=_parse_timestamp(m.group("ts")), level=_normalize_level(m.group("level")),
                        service=m.group("name") or "unknown", message=m.group("msg").strip(), raw=line)
    return None


# ---------------------------------------------------------------------------
# nginx / apache access logs
# ---------------------------------------------------------------------------

# 10.0.0.1 - - [28/Sep/2026:10:15:03 +0000] "GET /api/pay?id=7 HTTP/1.1" 502 157 "-" "curl/8.0"
_ACCESS_PATTERN = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] '
    r'"(?P<method>[A-Z]+) (?P<path>\S+)[^"]*" (?P<status>\d{3}) (?P<size>\S+)'
)


def _parse_access(line: str) -> LogEvent | None:
    m = _ACCESS_PATTERN.match(line)
    if not m:
        return None
    status = int(m.group("status"))
    level = "ERROR" if status >= 500 else "WARNING" if status >= 400 else "INFO"
    path = m.group("path").split("?", 1)[0]  # drop query so top-errors group by route
    return LogEvent(
        ts=_parse_strptime(m.group("ts"), "%d/%b/%Y:%H:%M:%S %z"),
        level=level,
        service="http",
        message=f"{m.group('method')} {path} {status}",
        raw=line,
    )


# ---------------------------------------------------------------------------
# syslog
# ---------------------------------------------------------------------------

# <34>1 2026-09-28T10:15:03.412Z host app 1234 ID47 - message
_SYSLOG_5424 = re.compile(
    rf"^<(?P<pri>\d{{1,3}})>\d (?P<ts>{_TS}|-) (?P<host>\S+) (?P<app>\S+) \S+ \S+ (?:-|\[.*?\]) ?(?P<msg>.*)$"
)
# [<34>]Sep 28 10:15:03 host program[123]: message
_SYSLOG_3164 = re.compile(
    r"^(?:<(?P<pri>\d{1,3})>)?(?P<ts>[A-Z][a-z]{2} [ \d]\d \d{2}:\d{2}:\d{2}) (?P<host>\S+) "
    r"(?P<app>[^\s:\[]+)(?:\[\d+\])?: (?P<msg>.*)$"
)
_ERROR_WORDS = re.compile(r"\b(error|err|fail(ed|ure)?|fatal|critical|panic|segfault|denied|refused)\b", re.I)
_WARN_WORDS = re.compile(r"\b(warn(ing)?|timeout|timed out|retry(ing)?)\b", re.I)


def _syslog_level(pri: str | None, msg: str) -> str:
    """RFC 5424 severity = PRI % 8 (0-3 error, 4 warning, 5-6 info, 7 debug); else keywords."""
    if pri is not None:
        sev = int(pri) % 8
        return "ERROR" if sev <= 3 else "WARNING" if sev == 4 else "DEBUG" if sev == 7 else "INFO"
    if _ERROR_WORDS.search(msg):
        return "ERROR"
    if _WARN_WORDS.search(msg):
        return "WARNING"
    return "INFO"


def _parse_syslog(line: str) -> LogEvent | None:
    m = _SYSLOG_5424.match(line)
    if m:
        ts = _parse_timestamp(m.group("ts")) if m.group("ts") != "-" else datetime.now(timezone.utc)
    else:
        m = _SYSLOG_3164.match(line)
        if not m:
            return None
        # RFC 3164 has no year or zone: assume the current UTC year.
        year = datetime.now(timezone.utc).year
        ts = _parse_strptime(f"{year} {m.group('ts')}", "%Y %b %d %H:%M:%S")
    msg = m.group("msg").strip()
    return LogEvent(ts=ts, level=_syslog_level(m.group("pri"), msg),
                    service=m.group("app"), message=msg, raw=line)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_PARSERS: dict[str, Callable[[str], LogEvent | None]] = {
    "json": _parse_json,
    "text": _parse_text,
    "python": _parse_text,
    "nginx": _parse_access,
    "syslog": _parse_syslog,
}

# Track parse failures for observability
parse_failures: int = 0


def _parse_auto(line: str) -> LogEvent | None:
    first = line[0]
    if first == "{":
        order = (_parse_json, _parse_text)
    elif first == "<":
        order = (_parse_syslog,)
    elif first.isdigit():
        # ISO timestamps and IPv4 access logs both start with a digit
        order = (_parse_text, _parse_access)
    else:
        order = (_parse_syslog, _parse_access, _parse_text, _parse_json)
    for parse in order:
        event = parse(line)
        if event is not None:
            return event
    return None


def parse_line(line: str, fmt: LogFormat = "auto") -> LogEvent | None:
    """
    Parse a single log line into a LogEvent.

    `auto` detects the format per line (cheap first-character dispatch), so one
    tailer can follow files of different formats. Returns None for malformed lines.
    """
    global parse_failures

    line = line.strip()
    if not line:
        return None

    event = _parse_auto(line) if fmt == "auto" else _PARSERS[fmt](line)

    if event is None:
        parse_failures += 1
        logger.debug("Failed to parse line: %s", line[:120])

    return event
