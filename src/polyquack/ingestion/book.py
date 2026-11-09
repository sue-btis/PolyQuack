import json
from dataclasses import dataclass

from polyquack.ingestion.models import BookLevels, Levels

DEPTH_FRACTION = 0.005


@dataclass(frozen=True)
class Snapshot:
    best_bid: float
    best_ask: float
    bid_notional_05: float
    ask_notional_05: float
    bid_levels: str
    ask_levels: str
    bid_reach: float
    ask_reach: float
    source_time_ms: int


class BookState:
    """In-memory book of one instrument.

    Valid only between a full book (channel message or REST resync) and the next connection loss.
    """

    def __init__(self) -> None:
        self.book: BookLevels | None = None
        self.invalid_cause = "no_book_received"

    def replace(self, book: BookLevels) -> None:
        self.book = book

    def invalidate(self, cause: str) -> None:
        self.book = None
        self.invalid_cause = cause


def build_snapshot(book: BookLevels) -> Snapshot | None:
    """Levels within 0.5% of the mid, plus how far the platform's levels actually reach.

    A side whose farthest delivered level is closer than 0.5% stays truncated at that reach;
    nothing is completed or estimated.
    """
    if not book.bids or not book.asks:
        return None
    best_bid = book.bids[0][0]
    best_ask = book.asks[0][0]
    mid = (best_bid + best_ask) / 2
    bid_floor = mid * (1 - DEPTH_FRACTION)
    ask_ceiling = mid * (1 + DEPTH_FRACTION)
    bids: Levels = [lv for lv in book.bids if lv[0] >= bid_floor]
    asks: Levels = [lv for lv in book.asks if lv[0] <= ask_ceiling]
    return Snapshot(
        best_bid=best_bid,
        best_ask=best_ask,
        bid_notional_05=sum(p * q for p, q in bids),
        ask_notional_05=sum(p * q for p, q in asks),
        bid_levels=json.dumps(bids),
        ask_levels=json.dumps(asks),
        bid_reach=(mid - min(p for p, _ in book.bids)) / mid,
        ask_reach=(max(p for p, _ in book.asks) - mid) / mid,
        source_time_ms=book.source_time_ms,
    )
