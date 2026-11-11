from dataclasses import dataclass

OPEN = "open"
HOLD = "hold"
REVERSE = "reverse"
CLOSE = "close"
NO_ACTION = "no_action"

LONG = "long"
SHORT = "short"


@dataclass(frozen=True)
class Choice:
    action: str
    side: str | None


def collecting_side(mean: float) -> str:
    """Polymarket side that collects funding: shorts receive when the spread is positive."""
    return SHORT if mean > 0 else LONG


def choose(mean: float, entry: float, exit_threshold: float, held: str | None) -> Choice:
    """Hysteresis rule on the mean spread; `held` is the Polymarket side of the open position."""
    side = collecting_side(mean)
    if held is None:
        return Choice(OPEN, side) if abs(mean) > entry else Choice(HOLD, None)
    if abs(mean) > entry and side != held:
        return Choice(REVERSE, side)
    if abs(mean) < exit_threshold:
        return Choice(CLOSE, None)
    return Choice(HOLD, None)
