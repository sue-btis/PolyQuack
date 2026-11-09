from dataclasses import dataclass

from polyquack.ingestion.models import Levels

# Float residue left after consuming a level exactly; far below any tradable amount.
_TOLERANCE = 1e-9


@dataclass(frozen=True)
class Fill:
    avg_price: float
    best_price: float
    quantity: float
    notional: float

    @property
    def slippage(self) -> float:
        return abs(self.avg_price - self.best_price) * self.quantity


def fill_notional(levels: Levels, notional: float) -> Fill | None:
    """Consume levels from the best one until `notional` (quote currency) is traded."""
    remaining = notional
    quantity = 0.0
    for price, size in levels:
        take = min(size, remaining / price)
        quantity += take
        remaining -= take * price
        if remaining <= _TOLERANCE:
            return Fill(notional / quantity, levels[0][0], quantity, notional)
    return None


def fill_quantity(levels: Levels, quantity: float) -> Fill | None:
    """Consume levels from the best one until `quantity` (asset units) is traded."""
    remaining = quantity
    notional = 0.0
    for price, size in levels:
        take = min(size, remaining)
        notional += take * price
        remaining -= take
        if remaining <= _TOLERANCE * quantity:
            return Fill(notional / quantity, levels[0][0], quantity, notional)
    return None
