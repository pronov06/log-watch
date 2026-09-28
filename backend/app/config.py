"""
Typed configuration via pydantic-settings.

All values come from environment variables or .env file.
The Settings class is the single source of truth for every tunable parameter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


class Settings(BaseSettings):
    """Application configuration – loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Input ---
    log_file_path: str = "./data/app.log"
    # Comma-separated files and/or globs (e.g. "/var/log/nginx/*.log,/var/log/app/*.jsonl").
    # Empty → tail LOG_FILE_PATH only.
    log_sources: str = ""
    log_format: Literal["auto", "text", "json", "python", "nginx", "syslog"] = "auto"
    tail_poll_interval_sec: float = Field(0.2, gt=0)
    source_rescan_sec: float = Field(2.0, gt=0)

    # --- Windowing ---
    window_seconds: int = Field(60, ge=1)
    eval_interval_sec: float = Field(5.0, gt=0)
    min_events_in_window: int = Field(20, ge=1)

    # --- Baseline ---
    baseline_warmup_samples: int = Field(24, ge=1)
    baseline_alpha: float = Field(0.05, gt=0, le=1)
    baseline_min_std: float = Field(0.01, gt=0)
    freeze_baseline_during_alert: bool = True
    baseline_path: str = "./data/baseline.json"

    # --- Detection thresholds ---
    z_low: float = 3.0
    z_medium: float = 4.5
    z_high: float = 6.5
    z_critical: float = 9.0
    abs_rate_critical: float = Field(0.50, gt=0, le=1)
    min_abs_rate: float = Field(0.05, ge=0, le=1)
    confirm_ticks: int = Field(2, ge=1)
    resolve_z: float = 2.0
    resolve_ticks: int = Field(3, ge=1)
    alert_cooldown_sec: int = Field(120, ge=0)

    # --- Alert publishing ---
    publish_mode: Literal["dry_run", "aws"] = "dry_run"
    aws_region: str = "ap-south-1"
    cw_log_group: str = "/hackathon/log-anomaly-detector"
    cw_log_stream: str = "alerts"
    sns_topic_arn: str = ""
    sns_min_severity: str = "MEDIUM"
    aws_endpoint_url: str = ""
    publish_max_retries: int = Field(3, ge=1, le=10)
    publish_backoff_base_sec: float = Field(1.0, ge=0)
    cw_metrics_enabled: bool = True
    cw_metrics_interval_sec: float = Field(60.0, ge=10)

    # --- API ---
    cors_origins: str = "http://localhost:5173"
    ring_buffer_size: int = Field(2000, ge=100)
    enable_sim: bool = True

    # --- App logging ---
    # JSON lines on stdout for the detector's own logs (CloudWatch/Loki friendly).
    log_json: bool = False
    app_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @model_validator(mode="after")
    def _check_consistency(self) -> "Settings":
        problems = []
        if not (self.z_low < self.z_medium < self.z_high < self.z_critical):
            problems.append("Z thresholds must increase: Z_LOW < Z_MEDIUM < Z_HIGH < Z_CRITICAL")
        if self.min_abs_rate >= self.abs_rate_critical:
            problems.append("MIN_ABS_RATE must be below ABS_RATE_CRITICAL")
        if self.eval_interval_sec > self.window_seconds:
            problems.append("EVAL_INTERVAL_SEC must not exceed WINDOW_SECONDS")
        if self.sns_min_severity.upper() not in SEVERITIES:
            problems.append(f"SNS_MIN_SEVERITY must be one of {', '.join(SEVERITIES)}")
        if self.sns_topic_arn and not self.sns_topic_arn.startswith("arn:aws"):
            problems.append("SNS_TOPIC_ARN must be a full ARN (arn:aws:sns:<region>:<account>:<name>)")
        if problems:
            raise ValueError("; ".join(problems))
        self.sns_min_severity = self.sns_min_severity.upper()
        return self

    def public_config(self) -> dict:
        """Non-secret settings the frontend needs (served by /api/config and the WS snapshot)."""
        return {
            "window_seconds": self.window_seconds,
            "eval_interval_sec": self.eval_interval_sec,
            "min_events_in_window": self.min_events_in_window,
            "z_low": self.z_low,
            "z_medium": self.z_medium,
            "z_high": self.z_high,
            "z_critical": self.z_critical,
            "abs_rate_critical": self.abs_rate_critical,
            "min_abs_rate": self.min_abs_rate,
            "confirm_ticks": self.confirm_ticks,
            "resolve_ticks": self.resolve_ticks,
            "baseline_warmup_samples": self.baseline_warmup_samples,
            "publish_mode": self.publish_mode,
            "sim_enabled": self.enable_sim,
        }

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def source_patterns(self) -> list[str]:
        patterns = [p.strip() for p in self.log_sources.split(",") if p.strip()]
        return patterns or [self.log_file_path]

    @property
    def log_path(self) -> Path:
        return Path(self.log_file_path)


def get_settings() -> Settings:
    """Factory – call once at startup. Invalid configuration stops the process with a clear message."""
    from pydantic import ValidationError

    try:
        return Settings()
    except ValidationError as exc:
        lines = [f"  {'.'.join(map(str, e['loc'])).upper() or 'CONFIG'}: {e['msg']}" for e in exc.errors()]
        raise SystemExit("Invalid configuration (check .env / environment):\n" + "\n".join(lines)) from None
