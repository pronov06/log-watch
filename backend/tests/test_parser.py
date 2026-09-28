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
