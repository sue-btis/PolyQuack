import logging
import sqlite3
from dataclasses import dataclass

from polyquack.evaluation.money import round_money
from polyquack.evaluation.preregistration import Preregistration, parse_preregistration
from polyquack.evaluation.readings import BookSnapshot, Reader
from polyquack.evaluation.rule import HOLD, LONG, NO_ACTION, OPEN, REVERSE, Choice, choose
from polyquack.evaluation.walk import Fill, fill_notional, fill_quantity
from polyquack.ingestion.models import DELISTED
from polyquack.ingestion.platforms import HYPERLIQUID, POLYMARKET
from polyquack.ingestion.service import _is_lock_contention
from polyquack.storage.db import Database
from polyquack.times import HOUR_MS, MINUTE_MS, floor_to, from_iso, iso

log = logging.getLogger(__name__)

PLATFORMS = (POLYMARKET, HYPERLIQUID)
POLYMARKET_FEE_CATEGORY = "crypto"
HYPERLIQUID_FEE_CATEGORY = ""

MISSING_RATE = "missing_rate"
NO_USABLE_SNAPSHOT = "no_usable_snapshot"
THIN_BOOK = "thin_book"
MISSING_FEE = "missing_fee"


class NoAction(Exception):
    def __init__(self, cause: str) -> None:
        super().__init__(cause)
        self.cause = cause


@dataclass
class EvaluationSummary:
    runs_started: int = 0
    decided: int = 0
    deferred: int = 0


@dataclass(frozen=True)
class Pair:
    id: int
    polymarket_instrument_id: int
    hyperliquid_instrument_id: int
    paired_ms: int


@dataclass(frozen=True)
class LiveRun:
    id: int
    starts_ms: int
    rule: Preregistration


@dataclass(frozen=True)
class HeldPosition:
    id: int
    side: str


@dataclass(frozen=True)
class PlannedTrade:
    platform: str
    kind: str
    side: str
    fill: Fill
    fee: float
    snapshot_minute_ms: int


@dataclass(frozen=True)
class Outcome:
    action: str
    cause: str | None
    spread: float | None
    trades: list[PlannedTrade]
    new_side: str | None


def latest_due(now_ms: int, decision_minute: int) -> int:
    offset = decision_minute * MINUTE_MS
    return floor_to(now_ms - offset, HOUR_MS) + offset


def evaluate(db: Database, now_ms: int) -> EvaluationSummary:
    """Start runs for new variants, then decide every due hour not yet decided, oldest first."""
    summary = EvaluationSummary()
    _start_runs(db, now_ms, summary)
    pairs = _load_pairs(db)
    for run in _live_runs(db):
        _evaluate_run(db, run, pairs, now_ms, summary)
    return summary


def _defer(error: sqlite3.OperationalError, what: str, summary: EvaluationSummary) -> None:
    if not _is_lock_contention(error):
        raise error
    log.error("%s: write failed, retried on the next run: %r", what, error)
    summary.deferred += 1


def _start_runs(db: Database, now_ms: int, summary: EvaluationSummary) -> None:
    rows = db.conn.execute(
        "SELECT v.id, v.preregistration, v.registered_at FROM variant v WHERE NOT EXISTS"
        " (SELECT 1 FROM run r WHERE r.variant_id = v.id AND r.mode = 'live') ORDER BY v.id"
    ).fetchall()
    for variant_id, text, registered_at in rows:
        minute = parse_preregistration(text).decision_minute
        # The first decision instant strictly after registration: no decision predates it.
        first = latest_due(from_iso(registered_at), minute) + HOUR_MS
        if first > now_ms:
            continue
        try:
            with db.conn:
                db.conn.execute(
                    "INSERT INTO run (variant_id, mode, starts_at, status)"
                    " VALUES (?, 'live', ?, 'in_progress')",
                    (variant_id, iso(first)),
                )
                db.conn.execute(
                    "UPDATE variant SET first_run_at = ? WHERE id = ?", (iso(now_ms), variant_id)
                )
        except sqlite3.OperationalError as error:
            _defer(error, f"variant {variant_id} run start", summary)
            continue
        summary.runs_started += 1


def _live_runs(db: Database) -> list[LiveRun]:
    rows = db.conn.execute(
        "SELECT r.id, r.starts_at, v.preregistration FROM run r"
        " JOIN variant v ON v.id = r.variant_id"
        " WHERE r.mode = 'live' AND r.status = 'in_progress' ORDER BY r.id"
    ).fetchall()
    return [LiveRun(row[0], from_iso(row[1]), parse_preregistration(row[2])) for row in rows]


def _load_pairs(db: Database) -> dict[int, Pair]:
    rows = db.conn.execute(
        "SELECT pair.id, pair.polymarket_instrument_id, pair.hyperliquid_instrument_id,"
        " pair.paired_at FROM pair JOIN asset a ON a.id = pair.asset_id ORDER BY a.symbol"
    ).fetchall()
    return {row[0]: Pair(row[0], row[1], row[2], from_iso(row[3])) for row in rows}


def _evaluate_run(
    db: Database, run: LiveRun, pairs: dict[int, Pair], now_ms: int, summary: EvaluationSummary
) -> None:
    decided = {
        (row[0], row[1])
        for row in db.conn.execute("SELECT pair_id, hour FROM decision WHERE run_id = ?", (run.id,))
    }
    blocked: set[int] = set()
    last_due = latest_due(now_ms, run.rule.decision_minute)
    for cutoff_ms in range(run.starts_ms, last_due + 1, HOUR_MS):
        status_reader = Reader(db.conn, cutoff_ms)
        due = [
            pair
            for pair in pairs.values()
            if pair.paired_ms <= cutoff_ms
            and pair.id not in blocked
            and (pair.id, iso(cutoff_ms)) not in decided
            and status_reader.pair_status(
                pair.polymarket_instrument_id, pair.hyperliquid_instrument_id
            )
            != DELISTED
        ]
        if not due:
            continue
        _accrue(db, run.id, pairs, cutoff_ms, blocked, summary)
        for pair in due:
            try:
                _decide(db, run, pair, cutoff_ms)
            except sqlite3.OperationalError as error:
                # Later hours of this pair depend on this one, so none is decided out of order.
                _defer(error, f"pair {pair.id} decision at {iso(cutoff_ms)}", summary)
                blocked.add(pair.id)
                continue
            summary.decided += 1


def _decide(db: Database, run: LiveRun, pair: Pair, cutoff_ms: int) -> None:
    reader = Reader(db.conn, cutoff_ms)
    held = _held_position(db, run.id, pair.id)
    outcome = _plan(db, reader, run.rule, pair, held, cutoff_ms)
    _record(db, run, pair.id, cutoff_ms, held, outcome, reader.data_until_ms)


def _held_position(db: Database, run_id: int, pair_id: int) -> HeldPosition | None:
    row = db.conn.execute(
        "SELECT id, polymarket_side FROM paper_position"
        " WHERE run_id = ? AND pair_id = ? AND status = 'open'",
        (run_id, pair_id),
    ).fetchone()
    return None if row is None else HeldPosition(row[0], row[1])


def _plan(
    db: Database,
    reader: Reader,
    rule: Preregistration,
    pair: Pair,
    held: HeldPosition | None,
    cutoff_ms: int,
) -> Outcome:
    hour_ms = cutoff_ms - rule.decision_minute * MINUTE_MS
    first_hour_ms = hour_ms - (rule.window_hours - 1) * HOUR_MS
    pm_rates = reader.funding_by_hour(pair.polymarket_instrument_id, first_hour_ms, hour_ms)
    hl_rates = reader.funding_by_hour(pair.hyperliquid_instrument_id, first_hour_ms, hour_ms)
    spreads = {hour: pm_rates[hour] - hl_rates[hour] for hour in pm_rates.keys() & hl_rates.keys()}
    if hour_ms not in spreads:
        return Outcome(NO_ACTION, MISSING_RATE, None, [], None)
    spread = spreads[hour_ms]
    mean = sum(spreads.values()) / len(spreads)
    choice = choose(mean, rule.entry, rule.exit, held.side if held else None)
    if choice.action == HOLD:
        return Outcome(HOLD, None, spread, [], None)
    try:
        trades = _plan_trades(db, reader, rule, pair, held, choice)
    except NoAction as no_action:
        return Outcome(NO_ACTION, no_action.cause, spread, [], None)
    return Outcome(choice.action, None, spread, trades, choice.side)


def _plan_trades(
    db: Database,
    reader: Reader,
    rule: Preregistration,
    pair: Pair,
    held: HeldPosition | None,
    choice: Choice,
) -> list[PlannedTrade]:
    max_age_ms = rule.snapshot_max_age_s * 1000
    snapshots = {
        POLYMARKET: reader.snapshot(pair.polymarket_instrument_id, max_age_ms),
        HYPERLIQUID: reader.snapshot(pair.hyperliquid_instrument_id, max_age_ms),
    }
    if any(snapshot is None for snapshot in snapshots.values()):
        raise NoAction(NO_USABLE_SNAPSHOT)
    fees = {
        POLYMARKET: reader.taker_fee(POLYMARKET, POLYMARKET_FEE_CATEGORY),
        HYPERLIQUID: reader.taker_fee(HYPERLIQUID, HYPERLIQUID_FEE_CATEGORY),
    }
    if any(fee is None for fee in fees.values()):
        raise NoAction(MISSING_FEE)
    trades: list[PlannedTrade] = []
    if held is not None:
        quantities = _open_quantities(db, held.id)
        trades += [
            _trade(p, "close", held.side, snapshots[p], fees[p], quantity=quantities[p])
            for p in PLATFORMS
        ]
    if choice.action in (OPEN, REVERSE) and choice.side is not None:
        trades += [
            _trade(p, "open", choice.side, snapshots[p], fees[p], notional=rule.size_per_leg)
            for p in PLATFORMS
        ]
    return trades


def _open_quantities(db: Database, position_id: int) -> dict[str, float]:
    rows = db.conn.execute(
        "SELECT p.name, t.quantity FROM paper_trade t JOIN platform p ON p.id = t.platform_id"
        " WHERE t.position_id = ? AND t.kind = 'open'",
        (position_id,),
    ).fetchall()
    return {name: float(quantity) for name, quantity in rows}


def _trade(
    platform: str,
    kind: str,
    polymarket_side: str,
    snapshot: BookSnapshot | None,
    taker: float | None,
    notional: float | None = None,
    quantity: float | None = None,
) -> PlannedTrade:
    assert snapshot is not None and taker is not None
    opens_with_buy = (polymarket_side == LONG) == (platform == POLYMARKET)
    buys = opens_with_buy if kind == "open" else not opens_with_buy
    levels = snapshot.asks if buys else snapshot.bids
    fill = (
        fill_notional(levels, notional)
        if notional is not None
        else fill_quantity(levels, quantity or 0.0)
    )
    if fill is None:
        raise NoAction(THIN_BOOK)
    return PlannedTrade(
        platform,
        kind,
        "buy" if buys else "sell",
        fill,
        round_money(taker * fill.notional),
        snapshot.minute_ms,
    )


def _record(
    db: Database,
    run: LiveRun,
    pair_id: int,
    cutoff_ms: int,
    held: HeldPosition | None,
    outcome: Outcome,
    data_until_ms: int | None,
) -> None:
    hour = iso(cutoff_ms)
    platform_ids = {name: db.platform_id(name) for name in PLATFORMS}
    with db.conn:
        db.conn.execute(
            "INSERT INTO decision"
            " (run_id, pair_id, hour, action, data_until, funding_spread, cause)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run.id,
                pair_id,
                hour,
                outcome.action,
                iso(cutoff_ms if data_until_ms is None else data_until_ms),
                outcome.spread,
                outcome.cause,
            ),
        )
        closing = [t for t in outcome.trades if t.kind == "close"]
        if held is not None and closing:
            db.conn.execute(
                "UPDATE paper_position SET closed_at = ?, status = 'closed' WHERE id = ?",
                (hour, held.id),
            )
            _insert_trades(db, held.id, hour, closing, platform_ids)
        opening = [t for t in outcome.trades if t.kind == "open"]
        if opening:
            cursor = db.conn.execute(
                "INSERT INTO paper_position (run_id, pair_id, polymarket_side, notional_per_leg,"
                " leverage, opened_at, status) VALUES (?, ?, ?, ?, ?, ?, 'open')",
                (
                    run.id,
                    pair_id,
                    outcome.new_side,
                    round_money(run.rule.size_per_leg),
                    run.rule.leverage,
                    hour,
                ),
            )
            assert cursor.lastrowid is not None
            _insert_trades(db, cursor.lastrowid, hour, opening, platform_ids)


def _insert_trades(
    db: Database,
    position_id: int,
    hour: str,
    trades: list[PlannedTrade],
    platform_ids: dict[str, int],
) -> None:
    db.conn.executemany(
        "INSERT INTO paper_trade (position_id, platform_id, kind, hour, side, avg_price,"
        " best_price, quantity, fee, slippage, snapshot_minute)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                position_id,
                platform_ids[t.platform],
                t.kind,
                hour,
                t.side,
                t.fill.avg_price,
                t.fill.best_price,
                t.fill.quantity,
                t.fee,
                round_money(t.fill.slippage),
                iso(t.snapshot_minute_ms),
            )
            for t in trades
        ],
    )


def _accrue(
    db: Database,
    run_id: int,
    pairs: dict[int, Pair],
    cutoff_ms: int,
    blocked: set[int],
    summary: EvaluationSummary,
) -> None:
    """Credit payments up to the cutoff, except to pairs whose earlier hour is still undecided.

    A deferred hour may turn out to be a close at that earlier instant, after which nothing
    later may have been credited.
    """
    positions = db.conn.execute(
        "SELECT id, pair_id, polymarket_side, notional_per_leg, opened_at, closed_at"
        " FROM paper_position WHERE run_id = ? AND opened_at < ?",
        (run_id, iso(cutoff_ms)),
    ).fetchall()
    reader = Reader(db.conn, cutoff_ms)
    platform_ids = {name: db.platform_id(name) for name in PLATFORMS}
    rows: list[tuple[int, int, str, float, float]] = []
    for position_id, pair_id, side, notional, opened_at, closed_at in positions:
        if pair_id in blocked:
            continue
        pair = pairs[pair_id]
        until_ms = cutoff_ms if closed_at is None else from_iso(closed_at)
        legs = (
            (POLYMARKET, pair.polymarket_instrument_id),
            (HYPERLIQUID, pair.hyperliquid_instrument_id),
        )
        for platform, instrument_id in legs:
            pays_when_rate_positive = (side == LONG) == (platform == POLYMARKET)
            for source_ms, rate in reader.payments(instrument_id, from_iso(opened_at), until_ms):
                amount = -rate * notional if pays_when_rate_positive else rate * notional
                rows.append(
                    (position_id, platform_ids[platform], iso(source_ms), rate, round_money(amount))
                )
    if not rows:
        return
    try:
        with db.conn:
            db.conn.executemany(
                "INSERT OR IGNORE INTO paper_funding_payment"
                " (position_id, platform_id, source_time, rate, amount) VALUES (?, ?, ?, ?, ?)",
                rows,
            )
    except sqlite3.OperationalError as error:
        _defer(error, f"funding accrual at {iso(cutoff_ms)}", summary)
