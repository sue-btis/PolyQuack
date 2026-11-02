from dataclasses import dataclass

Levels = list[tuple[float, float]]


ACTIVE = "active"
CLOSE_ONLY = "close_only"
DELISTED = "delisted"


@dataclass(frozen=True)
class InstrumentInfo:
    source_id: str
    source_symbol: str
    asset: str
    status: str = ACTIVE
    max_leverage: float | None = None
    maintenance_margin: float | None = None
    min_notional: float | None = None
    liquidation_fee: float | None = None


@dataclass(frozen=True)
class FeeRate:
    category: str
    tier: str
    taker: float
    maker: float
    # None means the platform publishes the rate, so it takes effect when first observed.
    effective_from_ms: int | None = None


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
