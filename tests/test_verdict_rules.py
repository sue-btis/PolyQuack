import pytest

from polyquack.evaluation.verdict import (
    CONTINUE,
    DISCARD,
    annual_return,
    limits_exceeded,
    max_collateral,
    outcome_for,
)
from polyquack.times import HOUR_MS


def test_dec5_a_return_exactly_at_the_criterion_continues_and_just_below_discards() -> None:
    assert outcome_for(0.10, 0.10) == CONTINUE
    assert outcome_for(0.10 + 1e-12, 0.10) == CONTINUE
    assert outcome_for(0.10 - 1e-12, 0.10) == DISCARD
    assert outcome_for(-0.5, 0.10) == DISCARD


def test_br003_the_annual_return_scales_the_horizon_return_to_365_days() -> None:
    assert annual_return(14.0, 1000.0, 28) == pytest.approx(14.0 / 1000.0 * 365 / 28)


def test_tst016_collateral_is_the_maximum_committed_at_once_not_the_sum() -> None:
    positions = [(0, 10 * HOUR_MS, 1000.0), (5 * HOUR_MS, 20 * HOUR_MS, 1000.0)]

    assert max_collateral(positions) == 2000.0


def test_tst016_positions_that_never_overlap_commit_only_one_at_a_time() -> None:
    positions = [(0, 5 * HOUR_MS, 1000.0), (6 * HOUR_MS, 9 * HOUR_MS, 1000.0)]

    assert max_collateral(positions) == 1000.0


def test_tst016_a_close_and_an_open_at_the_same_instant_do_not_overlap() -> None:
    positions = [(0, 5 * HOUR_MS, 1000.0), (5 * HOUR_MS, 9 * HOUR_MS, 1000.0)]

    assert max_collateral(positions) == 1000.0


def test_tst016_a_position_never_closed_stays_committed_and_no_positions_commit_nothing() -> None:
    assert max_collateral([(0, None, 1000.0), (HOUR_MS, 2 * HOUR_MS, 1000.0)]) == 2000.0
    assert max_collateral([]) == 0.0


def test_dec12_exactly_five_percent_of_hours_without_funding_is_kept_and_more_is_excluded() -> None:
    assert limits_exceeded(40, 2, 2400, 0) is None
    reason = limits_exceeded(40, 3, 2400, 0)
    assert reason is not None and "funding" in reason


def test_dec12_exactly_ten_percent_of_minutes_without_snapshot_is_kept_and_more_is_excluded() -> (
    None
):
    assert limits_exceeded(40, 0, 2400, 240) is None
    reason = limits_exceeded(40, 0, 2400, 241)
    assert reason is not None and "snapshot" in reason


def test_dec12_a_pair_with_no_expected_period_is_never_excluded() -> None:
    assert limits_exceeded(0, 0, 0, 0) is None


def test_f2_a_position_that_opens_and_closes_at_the_same_instant_still_commits() -> None:
    assert max_collateral([(5, 5, 1000.0)]) == 1000.0
    assert max_collateral([(0, 10, 1000.0), (5, 5, 1000.0)]) == 2000.0
