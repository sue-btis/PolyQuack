import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    db_path: Path
    assets: tuple[str, ...]
    min_interval_polymarket: float
    min_interval_hyperliquid: float

    @classmethod
    def from_env(cls) -> "Config":
        assets = os.environ.get("POLYQUACK_ASSETS", "BTC")
        return cls(
            db_path=Path(os.environ.get("POLYQUACK_DB", "polyquack.db")),
            assets=tuple(a.strip() for a in assets.split(",") if a.strip()),
            min_interval_polymarket=float(
                os.environ.get("POLYQUACK_MIN_INTERVAL_POLYMARKET", "0.8")
            ),
            min_interval_hyperliquid=float(
                os.environ.get("POLYQUACK_MIN_INTERVAL_HYPERLIQUID", "0.8")
            ),
        )
