"""
Typed configuration via pydantic-settings.

All values come from environment variables or .env file.
The Settings class is the single source of truth for every tunable parameter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration – loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Input ---
    log_file_path: str = "./data/app.log"
    log_format: Literal["auto", "text", "json"] = "auto"
    tail_poll_interval_sec: float = 0.2

    # --- Windowing ---
    window_seconds: int = 60
    eval_interval_sec: float = 5.0
    min_events_in_window: int = 20

    # --- Baseline ---
    baseline_warmup_samples: int = 24
    baseline_alpha: float = 0.05
    baseline_min_std: float = 0.01
    freeze_baseline_during_alert: bool = True
    baseline_path: str = "./data/baseline.json"

    # --- Detection thresholds ---
    z_low: float = 3.0
    z_medium: float = 4.5
    z_high: float = 6.5
    z_critical: float = 9.0
    abs_rate_critical: float = 0.50
    min_abs_rate: float = 0.05
    confirm_ticks: int = 2
    resolve_z: float = 2.0
    resolve_ticks: int = 3
    alert_cooldown_sec: int = 120

    # --- Alert publishing ---
    publish_mode: Literal["dry_run", "aws"] = "dry_run"
    aws_region: str = "ap-south-1"
    cw_log_group: str = "/hackathon/log-anomaly-detector"
    cw_log_stream: str = "alerts"
    sns_topic_arn: str = ""
    sns_min_severity: str = "MEDIUM"
    aws_endpoint_url: str = ""
    publish_max_retries: int = 3
    publish_backoff_base_sec: float = 1.0
    cw_metrics_enabled: bool = True
    cw_metrics_interval_sec: float = 60.0

    # --- API ---
    cors_origins: str = "http://localhost:5173"
    ring_buffer_size: int = 2000
    enable_sim: bool = True

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
    def log_path(self) -> Path:
        return Path(self.log_file_path)


def get_settings() -> Settings:
    """Factory – call once at startup and pass the instance around."""
    return Settings()
