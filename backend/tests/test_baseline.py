"""Tests for the EWMA baseline — warm-up, convergence, freeze, std floor."""

import math
import pytest
from app.baseline import Baseline


class TestWarmup:
    def test_not_ready_before_warmup(self):
        b = Baseline(warmup_samples=5, alpha=0.1, min_std=0.01)
        assert not b.ready
        for _ in range(4):
            b.warmup_add(0.02)
        assert not b.ready

    def test_ready_after_warmup(self):
        b = Baseline(warmup_samples=5, alpha=0.1, min_std=0.01)
        for _ in range(5):
            b.warmup_add(0.02)
        assert b.ready

    def test_warmup_seeds_mean(self):
        b = Baseline(warmup_samples=4, alpha=0.1, min_std=0.001)
        for val in [0.01, 0.02, 0.03, 0.04]:
            b.warmup_add(val)

        assert b.ready
        assert abs(b.mean - 0.025) < 0.001

    def test_warmup_seeds_std(self):
        b = Baseline(warmup_samples=4, alpha=0.1, min_std=0.001)
        for val in [0.01, 0.02, 0.03, 0.04]:
            b.warmup_add(val)

        # std of [0.01, 0.02, 0.03, 0.04] = sqrt(mean of squared diffs)
        expected_std = math.sqrt(sum((x - 0.025)**2 for x in [0.01, 0.02, 0.03, 0.04]) / 4)
        assert abs(b.std - expected_std) < 0.001


class TestEWMAUpdate:
    def test_update_moves_mean(self):
        b = Baseline(warmup_samples=2, alpha=0.5, min_std=0.001)
        b.warmup_add(0.02)
        b.warmup_add(0.02)

        old_mean = b.mean
        b.update(0.04)  # Higher than mean
        assert b.mean > old_mean

    def test_convergence(self):
        """After many updates at a constant rate, mean should converge to that rate."""
        b = Baseline(warmup_samples=2, alpha=0.1, min_std=0.001)
        b.warmup_add(0.01)
        b.warmup_add(0.01)

        # Update 100 times at 0.05 — should converge
        for _ in range(100):
            b.update(0.05)

        assert abs(b.mean - 0.05) < 0.005

    def test_update_before_ready_is_noop(self):
        b = Baseline(warmup_samples=5, alpha=0.1, min_std=0.01)
        b.update(0.10)  # Should do nothing
        assert not b.ready
        assert b.mean == 0.0


class TestStdFloor:
    def test_min_std_enforced(self):
        b = Baseline(warmup_samples=2, alpha=0.1, min_std=0.01)
        # Same value → zero variance
        b.warmup_add(0.02)
        b.warmup_add(0.02)

        assert b.std >= 0.01  # Floor enforced

    def test_many_identical_values(self):
        b = Baseline(warmup_samples=3, alpha=0.1, min_std=0.01)
        for _ in range(3):
            b.warmup_add(0.02)
        for _ in range(50):
            b.update(0.02)

        assert b.std >= 0.01


class TestState:
    def test_state_during_warmup(self):
        b = Baseline(warmup_samples=5, alpha=0.1, min_std=0.01, z_low=3.0)
        b.warmup_add(0.02)
        b.warmup_add(0.03)

        state = b.state()
        assert state["ready"] is False
        assert state["samples"] == 2

    def test_state_after_warmup(self):
        b = Baseline(warmup_samples=2, alpha=0.1, min_std=0.01, z_low=3.0)
        b.warmup_add(0.02)
        b.warmup_add(0.02)

        state = b.state()
        assert state["ready"] is True
        assert state["upper_band"] > state["mean"]
        assert state["lower_band"] >= 0.0


class TestPersistence:
    def test_save_and_load(self, tmp_path):
        path = tmp_path / "baseline.json"

        b1 = Baseline(warmup_samples=2, alpha=0.1, min_std=0.01, persist_path=path)
        b1.warmup_add(0.02)
        b1.warmup_add(0.03)
        b1.save()

        b2 = Baseline(warmup_samples=2, alpha=0.1, min_std=0.01, persist_path=path)
        assert b2.ready
        assert abs(b2.mean - b1.mean) < 0.0001

    def test_load_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        b = Baseline(warmup_samples=2, alpha=0.1, min_std=0.01, persist_path=path)
        assert not b.ready  # Should start fresh


# --- median/MAD and same-hour baselines -------------------------------------

import pytest  # noqa: E402

from app.baseline import RobustBaseline, SeasonalBaseline, make_baseline, robust_stats  # noqa: E402
from app.config import Settings  # noqa: E402


class TestRobustBaseline:
    def _ready(self, values, **kw):
        b = RobustBaseline(warmup_samples=len(values), history=200, min_std=0.001, **kw)
        for v in values:
            b.warmup_add(v)
        return b

    def test_outlier_barely_moves_median_but_drags_mean(self):
        calm = [0.02, 0.021, 0.019, 0.02, 0.022, 0.018] * 5
        robust = self._ready(calm + [0.60])
        ewma = Baseline(warmup_samples=len(calm) + 1, alpha=0.1, min_std=0.001)
        for v in calm + [0.60]:
            ewma.warmup_add(v)
        assert abs(robust.mean - 0.02) < 0.001
        assert robust.std < 0.005           # MAD ignores the burst
        assert ewma.mean > 0.035 and ewma.std > 0.09  # mean/std are hijacked by it

    def test_zero_mad_uses_floor(self):
        b = RobustBaseline(warmup_samples=5, min_std=0.01)
        for _ in range(5):
            b.warmup_add(0.0)
        assert b.ready and b.mean == 0.0 and b.std == 0.01

    def test_mad_scaled_to_sigma(self):
        med, scale = robust_stats([1, 2, 3, 4, 5], min_scale=0)
        assert med == 3 and scale == pytest.approx(1.4826)

    def test_history_is_bounded_and_rolls(self):
        b = RobustBaseline(warmup_samples=3, history=5, min_std=0.001)
        for v in (0.01, 0.01, 0.01):
            b.warmup_add(v)
        for _ in range(5):
            b.update(0.05)
        assert b.mean == pytest.approx(0.05)  # old samples rolled out

    def test_persistence_and_method_mismatch(self, tmp_path):
        path = tmp_path / "b.json"
        b1 = RobustBaseline(warmup_samples=2, min_std=0.01, persist_path=path)
        b1.warmup_add(0.02)
        b1.warmup_add(0.04)
        b1.save()
        b2 = RobustBaseline(warmup_samples=2, min_std=0.01, persist_path=path)
        assert b2.ready and b2.mean == pytest.approx(0.03)
        ewma = Baseline(warmup_samples=2, persist_path=path)  # different method → fresh start
        assert not ewma.ready


class TestSeasonalBaseline:
    DAY = 240  # compressed day: 24 slots of 10 s

    def _baseline(self, min_days=2, tolerance=0, path=None):
        inner = RobustBaseline(warmup_samples=1, min_std=0.001)
        inner.warmup_add(0.02)
        return SeasonalBaseline(inner, day_seconds=self.DAY, buckets_per_day=24, min_days=min_days,
                                tolerance_slots=tolerance, persist_path=path)

    def _fill(self, b, day, slot, rate, n=5):
        for i in range(n):
            b.observe(rate + 0.0001 * i, now=day * self.DAY + slot * 10 + i)

    def _ref(self, b, now):
        b.observe(0.02, now=now)  # the evaluator observes the current tick first (closes older slots)
        return b.reference(now=now)

    def test_uses_same_slot_from_previous_days(self):
        b = self._baseline()
        for day in (0, 1):
            self._fill(b, day, 2, 0.07)  # slot 2 is a busy "batch hour"
        ref = self._ref(b, 2 * self.DAY + 25)
        assert ref.source == "seasonal" and ref.center == pytest.approx(0.0702, abs=1e-3)

    def test_learns_breaching_samples(self):
        """A recurring 8% slot must become normal: observe() takes every reliable sample."""
        b = self._baseline(min_days=3)
        for day in range(3):
            self._fill(b, day, 5, 0.08)
        assert self._ref(b, 3 * self.DAY + 55).center == pytest.approx(0.0802, abs=1e-3)

    def test_falls_back_to_rolling_until_enough_days(self):
        b = self._baseline(min_days=3)
        for day in (0, 1):
            self._fill(b, day, 2, 0.07)
        assert self._ref(b, 2 * self.DAY + 25).source == "rolling"
        assert self._ref(b, 2 * self.DAY + 100).source == "rolling"  # other slot, no data

    def test_tolerance_covers_pattern_edges(self):
        """Pattern ends at slot 3 on previous days; at slot 4 (just after) it is still tolerated."""
        strict, tolerant = self._baseline(tolerance=0), self._baseline(tolerance=1)
        for b in (strict, tolerant):
            for day in (0, 1):
                self._fill(b, day, 3, 0.08)
                self._fill(b, day, 4, 0.02)
        at = 2 * self.DAY + 45  # slot 4
        assert self._ref(strict, at).center == pytest.approx(0.0202, abs=1e-3)
        assert self._ref(tolerant, at).center == pytest.approx(0.0802, abs=1e-3)

    def test_todays_samples_do_not_feed_todays_reference(self):
        b = self._baseline(min_days=1)
        self._fill(b, 0, 2, 0.02)
        for i in range(10):
            b.observe(0.30, now=self.DAY + 20 + i / 10)  # a drift today must not hide itself
        assert self._ref(b, self.DAY + 25).center == pytest.approx(0.0202, abs=1e-3)

    def test_one_bad_day_cannot_move_the_center(self):
        b = self._baseline(min_days=3)
        for day, rate in ((0, 0.07), (1, 0.07), (2, 0.40), (3, 0.07)):  # day 2 had an incident
            self._fill(b, day, 2, rate, n=6)
        ref = self._ref(b, 4 * self.DAY + 25)
        assert ref.source == "seasonal" and ref.center == pytest.approx(0.0703, abs=2e-3)

    def test_state_reports_source_and_days(self):
        b = self._baseline(min_days=1)
        self._fill(b, 0, 2, 0.05)
        b.observe(0.02, now=self.DAY + 20)
        st = b.state(now=self.DAY + 20)
        assert st["source"] == "seasonal" and st["seasonal_days"] == 1
        assert st["method"] == "median/MAD + same-hour"

    def test_profile_persists_as_summaries(self, tmp_path):
        path = tmp_path / "s.json"
        b = self._baseline(min_days=1, path=path)
        self._fill(b, 0, 2, 0.06)
        b.observe(0.02, now=100)  # closes slot 2
        b.save()
        b2 = self._baseline(min_days=1, path=path)
        assert b2.reference(now=self.DAY + 20).center == pytest.approx(0.0602, abs=1e-3)


def test_make_baseline_respects_config(tmp_path):
    p = str(tmp_path / "b.json")
    assert isinstance(make_baseline(Settings(baseline_path=p)), SeasonalBaseline)
    assert isinstance(make_baseline(Settings(baseline_path=p, seasonal_enabled=False)), RobustBaseline)
    assert isinstance(make_baseline(Settings(baseline_path=p, seasonal_enabled=False, baseline_method="ewma")), Baseline)


def test_rolling_baselines_ignore_observe():
    b = RobustBaseline(warmup_samples=1, min_std=0.001)
    b.warmup_add(0.02)
    b.observe(0.9)
    assert b.mean == 0.02
