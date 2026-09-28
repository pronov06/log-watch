"""Tests for the log parser — text and JSON formats, level normalization, edge cases."""

import pytest
from app.parser import parse_line, _normalize_level


class TestLevelNormalization:
    def test_standard_levels(self):
        assert _normalize_level("INFO") == "INFO"
        assert _normalize_level("ERROR") == "ERROR"
        assert _normalize_level("DEBUG") == "DEBUG"
        assert _normalize_level("WARNING") == "WARNING"

    def test_warn_to_warning(self):
        assert _normalize_level("WARN") == "WARNING"
        assert _normalize_level("warn") == "WARNING"

    def test_fatal_to_error(self):
        assert _normalize_level("FATAL") == "ERROR"
        assert _normalize_level("CRITICAL") == "ERROR"
        assert _normalize_level("SEVERE") == "ERROR"

    def test_unknown_defaults_to_info(self):
        assert _normalize_level("SOMETHING") == "INFO"
        assert _normalize_level("") == "INFO"


class TestParseTextFormat:
    def test_basic_text_line(self):
        line = '2026-09-28T10:15:03.412Z ERROR   service=payments msg="DB connection timeout" latency_ms=5021'
        event = parse_line(line, fmt="text")
        assert event is not None
        assert event.level == "ERROR"
        assert event.service == "payments"
        assert "DB connection timeout" in event.message

    def test_info_line(self):
        line = '2026-09-28T10:15:03.500Z INFO    service=auth msg="login ok" latency_ms=42'
        event = parse_line(line, fmt="text")
        assert event is not None
        assert event.level == "INFO"
        assert event.service == "auth"

    def test_warn_normalized(self):
        line = '2026-09-28T10:15:03.500Z WARN    service=gateway msg="slow response"'
        event = parse_line(line, fmt="text")
        assert event is not None
        assert event.level == "WARNING"

    def test_simple_format(self):
        line = "2026-09-28T10:15:03.412Z ERROR Something went wrong"
        event = parse_line(line, fmt="text")
        assert event is not None
        assert event.level == "ERROR"
        assert "Something went wrong" in event.message


class TestParseJsonFormat:
    def test_basic_json_line(self):
        line = '{"ts":"2026-09-28T10:15:03.412Z","level":"ERROR","service":"payments","msg":"DB connection timeout"}'
        event = parse_line(line, fmt="json")
        assert event is not None
        assert event.level == "ERROR"
        assert event.service == "payments"
        assert event.message == "DB connection timeout"

    def test_json_with_message_key(self):
        line = '{"ts":"2026-09-28T10:15:03Z","level":"INFO","service":"auth","message":"login ok"}'
        event = parse_line(line, fmt="json")
        assert event is not None
        assert event.message == "login ok"

    def test_json_fatal_normalized(self):
        line = '{"ts":"2026-09-28T10:15:03Z","level":"FATAL","service":"orders","msg":"crash"}'
        event = parse_line(line, fmt="json")
        assert event is not None
        assert event.level == "ERROR"


class TestAutoDetect:
    def test_auto_detects_json(self):
        line = '{"ts":"2026-09-28T10:15:03Z","level":"INFO","msg":"hello"}'
        event = parse_line(line, fmt="auto")
        assert event is not None
        assert event.level == "INFO"

    def test_auto_detects_text(self):
        line = '2026-09-28T10:15:03.412Z ERROR service=payments msg="timeout"'
        event = parse_line(line, fmt="auto")
        assert event is not None
        assert event.level == "ERROR"


class TestEdgeCases:
    def test_empty_line(self):
        assert parse_line("") is None
        assert parse_line("   ") is None

    def test_malformed_line(self):
        event = parse_line("this is not a valid log line at all")
        assert event is None

    def test_missing_timestamp_json(self):
        line = '{"level":"ERROR","msg":"no timestamp"}'
        event = parse_line(line, fmt="json")
        assert event is not None
        assert event.ts is not None  # Should default to now()

    def test_missing_service(self):
        line = '{"ts":"2026-09-28T10:15:03Z","level":"INFO","msg":"no service"}'
        event = parse_line(line, fmt="json")
        assert event is not None
        assert event.service == "unknown"

    def test_raw_preserved(self):
        line = '2026-09-28T10:15:03.412Z ERROR service=payments msg="test"'
        event = parse_line(line, fmt="text")
        assert event is not None
        assert event.raw == line


# --- real-world formats -----------------------------------------------------

from datetime import datetime, timezone  # noqa: E402


class TestRealWorldFormats:
    def test_python_logging_default_layout(self):
        e = parse_line("2026-09-28 10:15:03,412 ERROR app.db: connection reset by peer")
        assert (e.level, e.service, e.message) == ("ERROR", "app.db", "connection reset by peer")
        assert e.ts == datetime(2026, 9, 28, 10, 15, 3, 412000, tzinfo=timezone.utc)

    def test_python_logging_dash_layout(self):
        e = parse_line("2026-09-28 10:15:03,412 - payments.api - WARNING - slow query 812ms")
        assert (e.level, e.service, e.message) == ("WARNING", "payments.api", "slow query 812ms")

    def test_bracketed_level(self):
        e = parse_line("2026-09-28T10:15:03Z [CRITICAL] disk full")
        assert e.level == "ERROR" and e.message == "disk full"

    def test_timezone_offset_converted_to_utc(self):
        e = parse_line("2026-09-28T15:45:03+05:30 ERROR boom")
        assert e.ts == datetime(2026, 9, 28, 10, 15, 3, tzinfo=timezone.utc)

    def test_nginx_combined_5xx_is_error(self):
        line = '10.0.0.1 - - [28/Sep/2026:10:15:03 +0000] "GET /api/pay?id=7 HTTP/1.1" 502 157 "-" "curl/8.0"'
        e = parse_line(line)
        assert (e.level, e.service, e.message) == ("ERROR", "http", "GET /api/pay 502")
        assert e.ts == datetime(2026, 9, 28, 10, 15, 3, tzinfo=timezone.utc)

    def test_nginx_4xx_warning_2xx_info(self):
        base = '1.2.3.4 - bob [28/Sep/2026:10:15:03 +0000] "POST /login HTTP/1.1" {} 0'
        assert parse_line(base.format(404)).level == "WARNING"
        assert parse_line(base.format(200), fmt="nginx").level == "INFO"

    def test_syslog_5424_priority_level(self):
        e = parse_line("<11>1 2026-09-28T10:15:03.412Z web01 sshd 812 - - auth failure")
        assert (e.level, e.service, e.message) == ("ERROR", "sshd", "auth failure")  # 11 % 8 = 3 (err)

    def test_syslog_3164_keyword_level(self):
        e = parse_line("Sep 28 10:15:03 web01 kernel: nfs: server not responding, timed out")
        assert (e.level, e.service) == ("WARNING", "kernel")
        e = parse_line("Sep  8 10:15:03 web01 app[99]: payment failed for order 7")
        assert (e.level, e.service) == ("ERROR", "app")

    def test_syslog_3164_with_pri(self):
        e = parse_line("<14>Sep 28 10:15:03 web01 cron[1]: job done")
        assert e.level == "INFO"

    def test_ecs_json(self):
        line = '{"@timestamp":"2026-09-28T10:15:03Z","log":{"level":"error"},"service":{"name":"cart"},"message":"x"}'
        e = parse_line(line)
        assert (e.level, e.service, e.message) == ("ERROR", "cart", "x")

    def test_json_array_is_not_an_event(self):
        assert parse_line("[1, 2, 3]", fmt="json") is None
