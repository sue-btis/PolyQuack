import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

import httpx

from polyquack.completeness import render_completeness
from polyquack.config import Config
from polyquack.evaluation.preregistration import (
    InvalidPreregistration,
    preregister,
    render_variants,
)
from polyquack.evaluation.runner import ReevaluationError, evaluate, reevaluate
from polyquack.evaluation.verdict import render_verdict
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


def _configure_logging() -> None:
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )


def _preregister(config: Config, file: str) -> int:
    try:
        text = Path(file).read_text(encoding="utf-8")
        db = Database(config.db_path)
        registered = preregister(db, text, int(time.time() * 1000))
    except (OSError, InvalidPreregistration) as error:
        print(f"Cannot preregister: {error}", file=sys.stderr)
        return 1
    suffix = " (replaced; it had not run yet)" if registered.replaced else ""
    print(f"Preregistered {registered.method} variant {registered.number}{suffix}")
    return 0


def _evaluate(config: Config) -> int:
    _configure_logging()
    summary = evaluate(Database(config.db_path), int(time.time() * 1000))
    print(
        f"{summary.runs_started} runs started, {summary.decided} decisions,"
        f" {summary.deferred} deferred"
    )
    return 1 if summary.deferred else 0


def _reevaluate(config: Config, variant: str) -> int:
    _configure_logging()
    try:
        result = reevaluate(Database(config.db_path), int(variant), int(time.time() * 1000))
    except (ReevaluationError, ValueError) as error:
        print(f"Cannot re-evaluate: {error}", file=sys.stderr)
        return 1
    print(
        f"Re-evaluation run {result.run_id}: {result.status}, {result.summary.decided} decisions,"
        f" {result.summary.deferred} deferred"
    )
    return 1 if result.summary.deferred else 0


def _verdict(config: Config, run: str) -> int:
    try:
        text = render_verdict(Database(config.db_path, read_only=True), int(run))
    except ValueError:
        text = None
    if text is None:
        print(f"No run {run}", file=sys.stderr)
        return 1
    print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="polyquack")
    parser.add_argument(
        "command",
        choices=(
            "run",
            "status",
            "completeness",
            "preregister",
            "evaluate",
            "variants",
            "reevaluate",
            "verdict",
        ),
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="preregistration JSON for `preregister`, variant number for `reevaluate`, run id"
        " for `verdict`",
    )
    parser.add_argument("--days", type=int, default=7, help="window of `completeness`, in days")
    args = parser.parse_args(argv)
    if args.command == "preregister" and args.file is None:
        parser.error("preregister needs a FILE")
    if args.command in ("reevaluate", "verdict") and args.file is None:
        parser.error(
            f"{args.command} needs a {'VARIANT' if args.command == 'reevaluate' else 'RUN'}"
        )
    config = Config.from_env()
    try:
        if args.command == "preregister":
            return _preregister(config, args.file)
        if args.command in (
            "status",
            "completeness",
            "variants",
            "evaluate",
            "reevaluate",
            "verdict",
        ):
            if not Path(config.db_path).exists():
                print(f"No database at {config.db_path}", file=sys.stderr)
                return 1
            if args.command == "evaluate":
                return _evaluate(config)
            if args.command == "reevaluate":
                return _reevaluate(config, args.file)
            if args.command == "verdict":
                return _verdict(config, args.file)
            db = Database(config.db_path, read_only=True)
            now_ms = int(time.time() * 1000)
            if args.command == "variants":
                print(render_variants(db))
            elif args.command == "status":
                print(render_status(db, config.assets, now_ms))
            else:
                print(render_completeness(db, config.assets, args.days, now_ms))
            return 0
        _configure_logging()
        asyncio.run(_run(config))
    except KeyboardInterrupt:
        return 0
    except MigrationError as error:
        print(f"Cannot start: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
