"""
EWMA (Exponentially Weighted Moving Average) baseline for error rate.

The baseline learns what "normal" looks like and provides mean ± std for
the detector to compare against.

Key features:
- Warm-up phase: collects N samples to seed mean/std before detection starts
- EWMA update: mean = mean + α·(x - mean), var = (1-α)·(var + α·(x-mean)²)
- Freeze-on-anomaly: during an active alert, the baseline is NOT updated,
  preventing the anomaly from poisoning the "normal" baseline
- Std floor: BASELINE_MIN_STD prevents near-zero variance from causing
  infinite z-scores when the baseline is very flat
- Persistence: saves to JSON and reloads on restart (skips warm-up)
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

logger = logging.getLogger(__name__)


class Baseline:
    """
    EWMA baseline tracker for the error rate.

    During warm-up, accumulates raw samples and computes simple mean/std.
    After warm-up, uses exponentially weighted updates.
    """

    def __init__(
        self,
        warmup_samples: int = 24,
        alpha: float = 0.05,
        min_std: float = 0.01,
        z_low: float = 3.0,
        persist_path: str | Path | None = None,
    ):
        self.warmup_samples = warmup_samples
        self.alpha = alpha
        self.min_std = min_std
        self.z_low = z_low
        self.persist_path = Path(persist_path) if persist_path else None

        # State
        self.mean: float = 0.0
        self.var: float = 0.0
        self.std: float = min_std
        self.samples: int = 0
        self.ready: bool = False

        # Warm-up buffer
        self._warmup_buffer: list[float] = []

        # Try to load persisted state
        if self.persist_path:
            self._load()

    def warmup_add(self, rate: float) -> None:
        """
        Add a sample during the warm-up phase.

        Once warmup_samples are collected, compute initial mean/std and
        transition to the EWMA phase.
        """
        if self.ready:
            return

        self._warmup_buffer.append(rate)
        self.samples = len(self._warmup_buffer)

        if self.samples >= self.warmup_samples:
            # Seed the EWMA with simple statistics
            self.mean = sum(self._warmup_buffer) / len(self._warmup_buffer)
            variance = sum((x - self.mean) ** 2 for x in self._warmup_buffer) / len(self._warmup_buffer)
            self.var = variance
            self.std = max(math.sqrt(variance), self.min_std)
            self.ready = True
            self._warmup_buffer.clear()
            logger.info(
                "Baseline ready: mean=%.4f, std=%.4f (from %d samples)",
                self.mean, self.std, self.samples,
            )

    def update(self, rate: float) -> None:
        """
        Update the baseline with a new (non-anomalous) sample.

        Only call this when:
        1. The baseline is ready (past warm-up)
        2. No alert is currently open (freeze-on-anomaly)
        3. The current sample is not breaching

        Uses the EWMA update equations:
          diff = x - mean
          mean = mean + α * diff
          var  = (1 - α) * (var + α * diff²)
          std  = max(sqrt(var), min_std)
        """
        if not self.ready:
            return

        diff = rate - self.mean
        self.mean = self.mean + self.alpha * diff
        self.var = (1 - self.alpha) * (self.var + self.alpha * diff * diff)
        self.std = max(math.sqrt(self.var), self.min_std)
        self.samples += 1

    def state(self) -> dict:
        """
        Return the current baseline state for the API/frontend.

        upper_band and lower_band define the "normal" band drawn on the chart.
        """
        return {
            "mean": round(self.mean, 6),
            "std": round(self.std, 6),
            "samples": self.samples,
            "ready": self.ready,
            "warmup_needed": self.warmup_samples,
            "warmup_pct": 100.0 if self.ready else round(100.0 * self.samples / max(1, self.warmup_samples), 1),
            "upper_band": round(self.mean + self.z_low * self.std, 6),
            "lower_band": round(max(0.0, self.mean - self.z_low * self.std), 6),
        }

    def save(self) -> None:
        """Persist the baseline state to JSON."""
        if not self.persist_path:
            return
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "mean": self.mean,
                "var": self.var,
                "std": self.std,
                "samples": self.samples,
                "ready": self.ready,
            }
            self.persist_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            logger.debug("Baseline saved to %s", self.persist_path)
        except OSError as exc:
            logger.warning("Failed to save baseline: %s", exc)

    def _load(self) -> None:
        """Load persisted baseline state from JSON (skips warm-up on restart)."""
        if not self.persist_path or not self.persist_path.exists():
            return
        try:
            data = json.loads(self.persist_path.read_text(encoding="utf-8"))
            self.mean = data["mean"]
            self.var = data["var"]
            self.std = max(data["std"], self.min_std)
            self.samples = data["samples"]
            self.ready = data["ready"]
            logger.info(
                "Baseline loaded from %s: mean=%.4f, std=%.4f, ready=%s",
                self.persist_path, self.mean, self.std, self.ready,
            )
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("Failed to load baseline, starting fresh: %s", exc)
