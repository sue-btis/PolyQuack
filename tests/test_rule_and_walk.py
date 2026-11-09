import pytest

from polyquack.evaluation.money import round_money
from polyquack.evaluation.rule import Choice, choose
from polyquack.evaluation.walk import fill_notional, fill_quantity

ENTRY = 0.0002
EXIT = 0.00005


@pytest.mark.parametrize(
    ("mean", "held", "expected"),
    [
        (0.0003, None, Choice("open", "short")),
        (-0.0003, None, Choice("open", "long")),
        (0.0002, None, Choice("hold", None)),
        (-0.0002, None, Choice("hold", None)),
        (0.0001, None, Choice("hold", None)),
        (0.0, None, Choice("hold", None)),
        (0.0003, "short", Choice("hold", None)),
        (0.0001, "short", Choice("hold", None)),
        (0.00005, "short", Choice("hold", None)),
        (0.00004, "short", Choice("close", None)),
        (0.0, "short", Choice("close", None)),
        (-0.00004, "short", Choice("close", None)),
        (-0.0001, "short", Choice("hold", None)),
        (-0.0002, "short", Choice("hold", None)),
        (-0.0003, "short", Choice("reverse", "long")),
        (-0.0003, "long", Choice("hold", None)),
        (-0.00004, "long", Choice("close", None)),
        (0.0001, "long", Choice("hold", None)),
        (0.0003, "long", Choice("reverse", "short")),
    ],
)
def test_dec1_dec8_decision_rule_table(mean: float, held: str | None, expected: Choice) -> None:
    assert choose(mean, ENTRY, EXIT, held) == expected


def test_tst012_buying_walks_the_asks_for_the_notional() -> None:
    fill = fill_notional([(100.0, 5.0), (101.0, 10.0)], 1000.0)

    assert fill is not None
    quantity = 5.0 + 500.0 / 101.0
    assert fill.quantity == pytest.approx(quantity)
    assert fill.avg_price == pytest.approx(1000.0 / quantity)
    assert fill.best_price == 100.0
    assert fill.notional == pytest.approx(1000.0)
    assert fill.slippage == pytest.approx(1000.0 - 100.0 * quantity)


def test_tst012_a_book_whose_first_level_covers_the_notional_has_no_slippage() -> None:
    fill = fill_notional([(100.0, 50.0)], 1000.0)

    assert fill is not None
    assert (fill.avg_price, fill.quantity, fill.slippage) == (100.0, 10.0, 0.0)


def test_tst012_a_thin_side_cannot_be_filled_and_nothing_is_estimated() -> None:
    assert fill_notional([(100.0, 5.0), (101.0, 4.0)], 1000.0) is None
    assert fill_notional([], 1000.0) is None


def test_tst012_closing_walks_the_levels_for_the_open_quantity() -> None:
    fill = fill_quantity([(100.0, 6.0), (99.0, 10.0)], 8.0)

    assert fill is not None
    assert fill.notional == pytest.approx(600.0 + 198.0)
    assert fill.avg_price == pytest.approx(798.0 / 8.0)
    assert fill.slippage == pytest.approx((100.0 - 798.0 / 8.0) * 8.0)


def test_tst012_closing_more_than_the_depth_cannot_be_filled() -> None:
    assert fill_quantity([(100.0, 6.0)], 6.5) is None


def test_dec11_money_is_rounded_to_six_decimals_in_one_function() -> None:
    assert round_money(0.12345649) == 0.123456
    assert round_money(0.1234565001) == 0.123457
    assert round_money(-0.0000004) == 0.0
