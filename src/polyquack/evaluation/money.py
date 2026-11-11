MONEY_DECIMALS = 6


def round_money(value: float) -> float:
    """The only place money is rounded: micro-USD, because an hour of funding can be cents."""
    return round(value, MONEY_DECIMALS)
