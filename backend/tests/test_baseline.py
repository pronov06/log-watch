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
