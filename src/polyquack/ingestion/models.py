from dataclasses import dataclass

Levels = list[tuple[float, float]]


@dataclass(frozen=True)
class InstrumentInfo:
    source_id: str
    source_symbol: str
    asset: str


@dataclass(frozen=True)
class FundingPayment:
    source_time_ms: int
    rate: float


@dataclass(frozen=True)
class PriceQuote:
    mark_price: float
    index_price: float
    source_time_ms: int | None


@dataclass(frozen=True)
class BookLevels:
    """Full book as delivered by the platform: bids from highest, asks from lowest."""

    bids: Levels
    asks: Levels
    source_time_ms: int
