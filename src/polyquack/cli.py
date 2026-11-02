import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

import httpx

from polyquack.completeness import render_completeness
from polyquack.config import Config
from polyquack.ingestion.platforms import Hyperliquid, Platform, PolymarketPerps
from polyquack.ingestion.ratelimit import RateLimiter
from polyquack.ingestion.service import Service
from polyquack.status import render_status
from polyquack.storage.db import Database, MigrationError

HTTP_TIMEOUT_SECONDS = 15.0
USER_AGENT = "polyquack-ingestion"


async def _run(config: Config) -> None:
    db = Database(config.db_path)
    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, headers=headers) as http:
        platforms: dict[str, Platform] = {
            p.name: p
            for p in (
                PolymarketPerps(http, RateLimiter(config.min_interval_polymarket)),
                Hyperliquid(http, RateLimiter(config.min_interval_hyperliquid)),
            )
        }
        await Service(db, platforms, config.assets).run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="polyquack")
    parser.add_argument("command", choices=("run", "status", "completeness"))
    parser.add_argument("--days", type=int, default=7, help="window of `completeness`, in days")
    args = parser.parse_args(argv)
    config = Config.from_env()
    if args.command in ("status", "completeness"):
        if not Path(config.db_path).exists():
            print(f"No database at {config.db_path}", file=sys.stderr)
            return 1
        db = Database(config.db_path, read_only=True)
        now_ms = int(time.time() * 1000)
        if args.command == "status":
            print(render_status(db, config.assets, now_ms))
        else:
            print(render_completeness(db, config.assets, args.days, now_ms))
        return 0
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    try:
        asyncio.run(_run(config))
    except KeyboardInterrupt:
        return 0
    except MigrationError as error:
        print(f"Cannot start: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
