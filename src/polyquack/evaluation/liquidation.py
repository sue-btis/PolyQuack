def liquidation_price(
    is_long: bool, entry: float, leverage: float, maintenance_margin: float
) -> float:
    """Level where isolated equity equals maintenance margin; neither platform publishes it."""
    if is_long:
        return entry * (1 - 1 / leverage) / (1 - maintenance_margin)
    return entry * (1 + 1 / leverage) / (1 + maintenance_margin)


def is_liquidated(is_long: bool, mark: float, level: float) -> bool:
    return mark <= level if is_long else mark >= level


def liquidation_distance(is_long: bool, mark: float, level: float) -> float:
    return (mark - level) / mark if is_long else (level - mark) / mark
