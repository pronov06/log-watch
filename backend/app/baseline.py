"""
Baselines: what "normal" error rate looks like, as a (center, scale) pair.

The detector scores each tick as  z = (rate - center) / scale.

Three implementations share one interface (warmup_add / update / reference / state):

- RobustBaseline (default, BASELINE_METHOD=mad): median and MAD over a rolling history of
  calm samples. Error rates are mostly low with sudden spikes, which is not a bell curve:
  one burst drags a mean and inflates a standard deviation, which hides the next incident.
  The median and MAD barely move. MAD is scaled by 1.4826 so it estimates sigma for
  normal data, which keeps the Z_* thresholds meaningful.
- Baseline (BASELINE_METHOD=ewma): exponentially weighted mean/variance. Kept for comparison.
- SeasonalBaseline (SEASONAL_ENABLED=true): wraps either one. When the same hour of day has
  enough history from previous days (SEASONAL_MIN_DAYS), the tick is compared to that hour's
  median/MAD ("10 AM today vs 10 AM on past days") so a recurring busy or error-prone hour
  is not flagged as anomalous. Until then it falls back to the rolling baseline.

Common safeguards:
- Warm-up: no detection until BASELINE_WARMUP_SAMPLES reliable samples exist.
- Scale floor (BASELINE_MIN_STD): a flat or all-zero history makes MAD/std ~0 and every
  blip an "infinite" z-score. The floor, plus the absolute MIN_ABS_RATE gate in the
  detector, prevents that.
- Only calm samples are fed in (the Evaluator never passes breaching ticks, and freezes
  updates while an alert is open), so incidents do not become the new normal.
- Persistence: state is saved as JSON and reloaded on restart, which skips warm-up.
"""

from __future__ import annotations

import json
import logging
import math
import statistics
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class Reference:
    center: float
    scale: float
    source: str  # "rolling" | "seasonal"


def robust_stats(values, min_scale: float, low: bool = False) -> tuple[float, float]:
    """
    (median, max(1.4826 * MAD, min_scale)) of a non-empty sequence.

    low=True uses the lower median, so with an even count (e.g. 4 days) a level must be
    present in a strict majority of values to move the result.
    """
    med_fn = statistics.median_low if low else statistics.median
    med = med_fn(values)
    mad = med_fn([abs(v - med) for v in values])
    return med, max(MAD_TO_SIGMA * mad, min_scale)


class _RollingBase:
    """Shared warm-up bookkeeping, state() and persistence plumbing."""

    method = ""

    def __init__(self, warmup_samples: int, min_std: float, z_low: float, persist_path):
        self.warmup_samples = warmup_samples
        self.min_std = min_std
        self.z_low = z_low
        self.persist_path = Path(persist_path) if persist_path else None
        self.samples: int = 0
        self.ready: bool = False

    # Subclasses provide center/scale via `mean` / `std`
    mean: float
    std: float

    def reference(self, now: float | None = None) -> Reference:
        return Reference(self.mean, self.std, "rolling")

    def observe(self, rate: float, now: float | None = None) -> None:
        """Every reliable sample, calm or not. Rolling baselines only learn from calm ones."""

    def state(self, now: float | None = None) -> dict:
        """Baseline state for the API/frontend; the bands are drawn on the chart."""
        ref = self.reference(now)
        return {
            "method": self.method,
            "source": ref.source,
            "mean": round(ref.center, 6),
            "std": round(ref.scale, 6),
            "samples": self.samples,
            "ready": self.ready,
            "warmup_needed": self.warmup_samples,
            "warmup_pct": 100.0 if self.ready else round(100.0 * self.samples / max(1, self.warmup_samples), 1),
            "upper_band": round(ref.center + self.z_low * ref.scale, 6),
            "lower_band": round(max(0.0, ref.center - self.z_low * ref.scale), 6),
        }

    def _write(self, data: dict) -> None:
        if not self.persist_path:
            return
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            self.persist_path.write_text(json.dumps(data), encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to save baseline: %s", exc)

    def _read(self) -> dict | None:
        if not self.persist_path or not self.persist_path.exists():
            return None
        try:
            data = json.loads(self.persist_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load baseline, starting fresh: %s", exc)
            return None
        if data.get("method", "EWMA") != self.method:
            logger.info("Persisted baseline is %s, configured %s: starting fresh",
                        data.get("method", "EWMA"), self.method)
            return None
        return data


class Baseline(_RollingBase):
    """
    EWMA baseline: mean += α·(x − mean); var = (1 − α)·(var + α·(x − mean)²).

    During warm-up it accumulates raw samples and seeds mean/std with plain statistics.
    """

    method = "EWMA"

    def __init__(
        self,
        warmup_samples: int = 24,
        alpha: float = 0.05,
        min_std: float = 0.01,
        z_low: float = 3.0,
        persist_path: str | Path | None = None,
    ):
        super().__init__(warmup_samples, min_std, z_low, persist_path)
        self.alpha = alpha
        self.mean: float = 0.0
        self.var: float = 0.0
        self.std: float = min_std
        self._warmup_buffer: list[float] = []
        self._load()

    def warmup_add(self, rate: float, now: float | None = None) -> None:
        if self.ready:
            return
        self._warmup_buffer.append(rate)
        self.samples = len(self._warmup_buffer)
        if self.samples >= self.warmup_samples:
            self.mean = sum(self._warmup_buffer) / len(self._warmup_buffer)
            self.var = sum((x - self.mean) ** 2 for x in self._warmup_buffer) / len(self._warmup_buffer)
            self.std = max(math.sqrt(self.var), self.min_std)
            self.ready = True
            self._warmup_buffer.clear()
            logger.info("Baseline ready (EWMA): mean=%.4f std=%.4f", self.mean, self.std)

    def update(self, rate: float, now: float | None = None) -> None:
        """Fold in one calm sample (the Evaluator decides which samples are calm)."""
        if not self.ready:
            return
        diff = rate - self.mean
        self.mean = self.mean + self.alpha * diff
        self.var = (1 - self.alpha) * (self.var + self.alpha * diff * diff)
        self.std = max(math.sqrt(self.var), self.min_std)
        self.samples += 1

    def save(self) -> None:
        self._write({"method": self.method, "mean": self.mean, "var": self.var, "std": self.std,
                     "samples": self.samples, "ready": self.ready})

    def _load(self) -> None:
        data = self._read()
        if not data:
            return
        try:
            self.mean, self.var = data["mean"], data["var"]
            self.std = max(data["std"], self.min_std)
            self.samples, self.ready = data["samples"], data["ready"]
            logger.info("Baseline loaded (EWMA): mean=%.4f std=%.4f", self.mean, self.std)
        except KeyError as exc:
            logger.warning("Persisted baseline incomplete (%s), starting fresh", exc)


# Explicit alias for readers comparing methods
EwmaBaseline = Baseline


class RobustBaseline(_RollingBase):
    """Median ± scaled MAD over the last `history` calm samples."""

    method = "median/MAD"

    def __init__(
        self,
        warmup_samples: int = 24,
        history: int = 360,
        min_std: float = 0.01,
        z_low: float = 3.0,
        persist_path: str | Path | None = None,
    ):
        super().__init__(warmup_samples, min_std, z_low, persist_path)
        self._hist: deque[float] = deque(maxlen=max(history, warmup_samples))
        self._center: float = 0.0
        self._scale: float = min_std
        self._dirty = False
        self._load()

    def _refresh(self) -> None:
        if self._dirty and self._hist:
            self._center, self._scale = robust_stats(self._hist, self.min_std)
        self._dirty = False

    @property
    def mean(self) -> float:
        self._refresh()
        return self._center

    @property
    def std(self) -> float:
        self._refresh()
        return self._scale

    def warmup_add(self, rate: float, now: float | None = None) -> None:
        if self.ready:
            return
        self._hist.append(rate)
        self.samples = len(self._hist)
        self._dirty = True
        if self.samples >= self.warmup_samples:
            self.ready = True
            logger.info("Baseline ready (median/MAD): median=%.4f scale=%.4f", self.mean, self.std)

    def update(self, rate: float, now: float | None = None) -> None:
        if not self.ready:
            return
        self._hist.append(rate)
        self.samples += 1
        self._dirty = True

    def save(self) -> None:
        self._write({"method": self.method, "history": list(self._hist),
                     "samples": self.samples, "ready": self.ready})

    def _load(self) -> None:
        data = self._read()
        if not data:
            return
        try:
            self._hist.extend(data["history"])
            self.samples, self.ready = data["samples"], data["ready"]
            self._dirty = True
            logger.info("Baseline loaded (median/MAD): %d samples", len(self._hist))
        except KeyError as exc:
            logger.warning("Persisted baseline incomplete (%s), starting fresh", exc)


class SeasonalBaseline:
    """
    Same-time-of-day baseline with rolling fallback ("10 AM today vs 10 AM on past days").

    Learning. The day is split into short slots (default 5 min). *Every* reliable sample is
    recorded, including ones that breach the rolling baseline: a batch job that raises
    errors to 8% at 02:00 every night must become "normal for 02:00", which can't happen if
    only calm samples are kept. When a slot is over, its samples are summarised to
    (median, scaled MAD), so memory and the persisted file stay small.

    Reference at time t. For each slot within ±`tolerance_slots` of t (default ±15 min), take
    the previous days' summaries for that slot and combine them robustly:
        center = median of the per-day medians
        scale  = max(median of per-day scales, scaled MAD of the per-day medians)
    A slot needs `min_days` previous days of data. Lower medians are used, so a level must
    be present on a strict majority of those days. The reference is the slot with the
    highest center among the nearby slots, together with that slot's scale, so a pattern
    that starts or ends a few minutes off its usual time doesn't alert on the edge. It stays
    robust: to be treated as normal, a level must recur around this time on most previous
    days, so one or two bad days (yesterday's 10 AM incident) cannot move it. With no qualifying slot, the wrapped
    rolling baseline is used. Today never feeds today's reference, so a slow drift today
    can't hide itself.

    `day_seconds` is configurable so the idea can be demonstrated live with a compressed
    "day" (e.g. 600 s) instead of waiting three real days.
    """

    MIN_SAMPLES_PER_SLOT = 3

    def __init__(
        self,
        inner,
        day_seconds: int = 86_400,
        buckets_per_day: int = 288,
        min_days: int = 3,
        max_days: int = 7,
        tolerance_slots: int = 3,
        persist_path: str | Path | None = None,
    ):
        self.inner = inner
        self.method = f"{inner.method} + same-hour"
        self.day_seconds = day_seconds
        self.buckets_per_day = buckets_per_day
        self.bucket_seconds = day_seconds / buckets_per_day
        self.min_days = min_days
        self.max_days = max_days
        self.tolerance = tolerance_slots
        self.persist_path = Path(persist_path) if persist_path else None
        self._raw: dict[int, list[float]] = {}                 # absolute slot → samples (open slots)
        self._summary: dict[int, tuple[float, float]] = {}     # absolute slot → (median, scale)
        self._cache: dict[int, Reference | None] = {}
        self._load()

    # --- delegated rolling state ---
    @property
    def ready(self) -> bool:
        return self.inner.ready

    @property
    def samples(self) -> int:
        return self.inner.samples

    @property
    def mean(self) -> float:
        return self.inner.mean

    @property
    def std(self) -> float:
        return self.inner.std

    @property
    def warmup_samples(self) -> int:
        return self.inner.warmup_samples

    @property
    def z_low(self) -> float:
        return self.inner.z_low

    def _abs_slot(self, now: float) -> int:
        return int(now // self.bucket_seconds)

    def warmup_add(self, rate: float, now: float | None = None) -> None:
        self.inner.warmup_add(rate, now)

    def update(self, rate: float, now: float | None = None) -> None:
        self.inner.update(rate, now)

    def observe(self, rate: float, now: float | None = None) -> None:
        slot = self._abs_slot(time.time() if now is None else now)
        # Time only moves forward: any other open slot is complete, so summarise it.
        for done in [s for s in self._raw if s != slot]:
            vs = self._raw.pop(done)
            if len(vs) >= self.MIN_SAMPLES_PER_SLOT:
                self._summary[done] = robust_stats(vs, 0.0)
        self._raw.setdefault(slot, []).append(rate)
        oldest = slot - (self.max_days + 1) * self.buckets_per_day
        if len(self._summary) > (self.max_days + 2) * self.buckets_per_day:
            for s in [s for s in self._summary if s < oldest]:
                del self._summary[s]

    def _slot_reference(self, slot: int) -> tuple[float, float] | None:
        """Cross-day robust (center, scale) for one slot, from previous days only."""
        per_day = [self._summary[slot - k * self.buckets_per_day]
                   for k in range(1, self.max_days + 1)
                   if slot - k * self.buckets_per_day in self._summary]
        if len(per_day) < self.min_days:
            return None
        center, between_days = robust_stats([m for m, _ in per_day], 0.0, low=True)
        within_day = statistics.median_low([s for _, s in per_day])
        return center, max(within_day, between_days)

    def days_for_slot(self, now: float) -> int:
        slot = self._abs_slot(now)
        return sum(1 for k in range(1, self.max_days + 1) if slot - k * self.buckets_per_day in self._summary)

    def reference(self, now: float | None = None) -> Reference:
        slot = self._abs_slot(time.time() if now is None else now)
        if slot not in self._cache:
            # Previous days are immutable during today, so this is fixed for the slot.
            if len(self._cache) > 64:
                self._cache.clear()
            refs = [r for off in range(-self.tolerance, self.tolerance + 1)
                    if (r := self._slot_reference(slot + off)) is not None]
            if refs:
                center, scale = max(refs)  # the highest robust level seen around this time
                self._cache[slot] = Reference(center, max(scale, self.inner.min_std), "seasonal")
            else:
                self._cache[slot] = None
        return self._cache[slot] or self.inner.reference(now)

    def state(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        st = _RollingBase.state(self, now)  # uses self.reference / warmup fields
        st["seasonal_days"] = self.days_for_slot(now)
        st["seasonal_min_days"] = self.min_days
        return st

    def save(self) -> None:
        self.inner.save()
        if not self.persist_path:
            return
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"day_seconds": self.day_seconds, "buckets_per_day": self.buckets_per_day,
                    "summary": {str(s): list(v) for s, v in self._summary.items()}}
            self.persist_path.write_text(json.dumps(data), encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to save seasonal profile: %s", exc)

    def _load(self) -> None:
        if not self.persist_path or not self.persist_path.exists():
            return
        try:
            data = json.loads(self.persist_path.read_text(encoding="utf-8"))
            if (data["day_seconds"], data["buckets_per_day"]) != (self.day_seconds, self.buckets_per_day):
                logger.info("Seasonal profile has a different day layout: starting fresh")
                return
            self._summary = {int(s): (float(m), float(sc)) for s, (m, sc) in data["summary"].items()}
            logger.info("Seasonal profile loaded: %d slot summaries", len(self._summary))
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            logger.warning("Failed to load seasonal profile, starting fresh: %s", exc)


def make_baseline(cfg, suffix: str = ""):
    """
    Build the configured baseline (method + optional same-hour wrapper).

    `suffix` separates the persisted state of additional baselines (e.g. ".fast" for the
    fast window, whose error-rate distribution differs from the main window's).
    """
    path = Path(cfg.baseline_path)
    if suffix:
        path = path.with_name(path.stem + suffix + path.suffix)
    if cfg.baseline_method == "ewma":
        inner = Baseline(cfg.baseline_warmup_samples, cfg.baseline_alpha, cfg.baseline_min_std,
                         cfg.z_low, persist_path=path)
    else:
        history = max(cfg.baseline_warmup_samples, int(cfg.baseline_history_sec / cfg.eval_interval_sec))
        inner = RobustBaseline(cfg.baseline_warmup_samples, history, cfg.baseline_min_std,
                               cfg.z_low, persist_path=path)
    if not cfg.seasonal_enabled:
        return inner
    return SeasonalBaseline(
        inner,
        day_seconds=cfg.seasonal_day_seconds,
        buckets_per_day=cfg.seasonal_buckets_per_day,
        min_days=cfg.seasonal_min_days,
        max_days=cfg.seasonal_max_days,
        tolerance_slots=cfg.seasonal_tolerance_slots,
        persist_path=path.with_name(path.stem + ".seasonal.json"),
    )
