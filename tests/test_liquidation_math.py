import pytest

from polyquack.evaluation.liquidation import (
    is_liquidated,
    liquidation_distance,
    liquidation_price,
)


def test_dec7_a_long_at_2x_with_no_maintenance_margin_liquidates_at_half_the_entry() -> None:
    assert liquidation_price(True, 100.0, 2.0, 0.0) == pytest.approx(50.0)


def test_dec7_a_short_at_2x_with_no_maintenance_margin_liquidates_at_one_and_a_half_times() -> None:
    assert liquidation_price(False, 100.0, 2.0, 0.0) == pytest.approx(150.0)


def test_dec7_maintenance_margin_moves_the_level_toward_the_entry() -> None:
    assert liquidation_price(True, 100.0, 2.0, 0.025) == pytest.approx(100 * 0.5 / 0.975)
    assert liquidation_price(False, 100.0, 2.0, 0.025) == pytest.approx(100 * 1.5 / 1.025)


def test_dec7_a_long_is_liquidated_at_or_below_its_level_and_a_short_at_or_above() -> None:
    assert is_liquidated(True, 50.0, 50.0)
    assert is_liquidated(True, 49.0, 50.0)
    assert not is_liquidated(True, 50.01, 50.0)
    assert is_liquidated(False, 150.0, 150.0)
    assert is_liquidated(False, 151.0, 150.0)
    assert not is_liquidated(False, 149.99, 150.0)


def test_dec7_distance_is_positive_until_the_level_and_negative_beyond_it() -> None:
    assert liquidation_distance(True, 100.0, 50.0) == pytest.approx(0.5)
    assert liquidation_distance(False, 100.0, 150.0) == pytest.approx(0.5)
    assert liquidation_distance(True, 40.0, 50.0) == pytest.approx(-0.25)
    assert liquidation_distance(False, 200.0, 150.0) == pytest.approx(-0.25)
