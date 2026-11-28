"""Lead-lag statistics used by the relationship tests."""

from __future__ import annotations

import pytest

from cmci.relationships import bh_qvalues, block_bootstrap_ci, fisher_p_value, spearman


def test_spearman_monotonic_and_reversed():
    xs = [1, 2, 3, 4, 5]
    assert spearman(xs, [10, 20, 30, 40, 50]) == pytest.approx(1.0)
    assert spearman(xs, [50, 40, 30, 20, 10]) == pytest.approx(-1.0)


def test_spearman_handles_ties():
    xs = [1, 2, 2, 3]
    ys = [1, 2, 3, 4]
    value = spearman(xs, ys)
    assert value is not None
    assert 0.8 < value < 1.0


def test_fisher_p_value_is_small_for_strong_relation():
    assert fisher_p_value(0.0, 100) == pytest.approx(1.0)
    assert fisher_p_value(0.5, 100) < 1e-6


def test_benjamini_hochberg_is_monotone_and_bounded():
    q_values = bh_qvalues([0.001, 0.02, 0.5, 0.9])
    assert all(0.0 <= value <= 1.0 for value in q_values)
    assert q_values[0] <= q_values[1] <= q_values[-1]


def test_block_bootstrap_is_deterministic():
    xs = list(range(120))
    ys = [(value * 3) % 37 for value in xs]
    first = block_bootstrap_ci(xs, ys, reps=200, seed=7)
    second = block_bootstrap_ci(xs, ys, reps=200, seed=7)
    assert first == second
    assert first[0] is not None and first[1] is not None
    assert first[0] <= first[1]