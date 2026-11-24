import logging
import sqlite3
from bisect import bisect_right
from dataclasses import dataclass, replace

from polyquack.evaluation.liquidation import (
    is_liquidated,
    liquidation_distance,
    liquidation_price,
)
from polyquack.evaluation.migration import add_missing_columns
from polyquack.evaluation.money import round_money
from polyquack.evaluation.preregistration import Preregistration, parse_preregistration
from polyquack.evaluation.readings import BookSnapshot, Reader
from polyquack.evaluation.rule import (
    CLOSE,
    HOLD,
    LONG,
    NO_ACTION,
    OPEN,
    REVERSE,
    Choice,
    choose,
)
from polyquack.evaluation.verdict import finish_run
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
FEE_CATEGORY = {POLYMARKET: POLYMARKET_FEE_CATEGORY, HYPERLIQUID: HYPERLIQUID_FEE_CATEGORY}
REEVALUATION = "reevaluation"
DAY_MS = 24 * HOUR_MS

MISSING_RATE = "missing_rate"
NO_USABLE_SNAPSHOT = "no_usable_snapshot"
THIN_BOOK = "thin_book"
MISSING_FEE = "missing_fee"


class ReevaluationError(Exception):
    pass


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
class Reevaluation:
    run_id: int
    status: str
    summary: EvaluationSummary


@dataclass(frozen=True)
class Pair:
    id: int
    polymarket_instrument_id: int
    hyperliquid_instrument_id: int
    paired_ms: int
    symbol: str = ""


@dataclass(frozen=True)
class LiveRun:
    id: int
    starts_ms: int
    rule: Preregistration
    mode: str = "live"
    measured_from_ms: int = 0

    @property
    def horizon_end_ms(self) -> int:
        return self.starts_ms + self.rule.horizon_days * DAY_MS

    @property
    def last_instant_ms(self) -> int:
        return self.horizon_end_ms - HOUR_MS


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
class ActivePosition:
    id: int
    pair_id: int
    side: str
    notional: float
    leverage: float
    opened_ms: int
    status: str


@dataclass(frozen=True)
class Leg:
    platform: str
    instrument_id: int
    is_long: bool
    entry: float
    quantity: float


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
    add_missing_columns(db.conn)
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
                    "INSERT INTO run (variant_id, mode, starts_at, status, measured_from)"
                    " VALUES (?, 'live', ?, 'in_progress', ?)",
                    (variant_id, iso(first), iso(first)),
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
        "SELECT r.id, r.starts_at, v.preregistration, r.measured_from FROM run r"
        " JOIN variant v ON v.id = r.variant_id"
        " WHERE r.mode = 'live' AND r.status = 'in_progress' ORDER BY r.id"
    ).fetchall()
    return [
        LiveRun(
            row[0],
            from_iso(row[1]),
            parse_preregistration(row[2]),
            measured_from_ms=0 if row[3] is None else from_iso(row[3]),
        )
        for row in rows
    ]


def _load_pairs(db: Database) -> dict[int, Pair]:
    rows = db.conn.execute(
        "SELECT pair.id, pair.polymarket_instrument_id, pair.hyperliquid_instrument_id,"
        " pair.paired_at, a.symbol FROM pair JOIN asset a ON a.id = pair.asset_id"
        " ORDER BY a.symbol"
    ).fetchall()
    return {row[0]: Pair(row[0], row[1], row[2], from_iso(row[3]), row[4]) for row in rows}


def _evaluate_run(
    db: Database, run: LiveRun, pairs: dict[int, Pair], now_ms: int, summary: EvaluationSummary
) -> None:
    deferred_before = summary.deferred
    run = _with_measure_floor(db, run)
    decided = {
        (row[0], row[1])
        for row in db.conn.execute("SELECT pair_id, hour FROM decision WHERE run_id = ?", (run.id,))
    }
    blocked: set[int] = set()
    last_due = min(latest_due(now_ms, run.rule.decision_minute), run.last_instant_ms)
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
        _measure(db, run, pairs, cutoff_ms, blocked, summary)
        _accrue(db, run.id, pairs, cutoff_ms, blocked, summary)
        for pair in due:
            if pair.id in blocked:
                continue
            try:
                _decide(db, run, pair, cutoff_ms)
            except sqlite3.OperationalError as error:
                # Later hours of this pair depend on this one, so none is decided out of order.
                _defer(error, f"pair {pair.id} decision at {iso(cutoff_ms)}", summary)
                blocked.add(pair.id)
                continue
            summary.decided += 1
    if summary.deferred > deferred_before or now_ms < run.last_instant_ms:
        return
    _close_at_horizon(db, run, pairs, now_ms, summary)
    if now_ms >= run.horizon_end_ms and summary.deferred == deferred_before:
        try:
            finish_run(db, run, list(pairs.values()), now_ms, run.mode == REEVALUATION)
        except sqlite3.OperationalError as error:
            _defer(error, f"run {run.id} verdict", summary)


def _with_measure_floor(db: Database, run: LiveRun) -> LiveRun:
    """Fix the first minute this run may measure; a run stored before the step existed has none.

    Measuring such a run from its positions' openings would liquidate legs at minutes the
    earlier code had already decided and credited funding past, so it starts after the latest
    decision it already holds.
    """
    stored = db.conn.execute("SELECT measured_from FROM run WHERE id = ?", (run.id,)).fetchone()[0]
    if stored is None:
        latest = db.conn.execute(
            "SELECT max(hour) FROM decision WHERE run_id = ?", (run.id,)
        ).fetchone()[0]
        floor_ms = run.starts_ms if latest is None else from_iso(latest) + MINUTE_MS
        with db.conn:
            db.conn.execute(
                "UPDATE run SET measured_from = ? WHERE id = ?", (iso(floor_ms), run.id)
            )
        return replace(run, measured_from_ms=floor_ms)
    return replace(run, measured_from_ms=from_iso(stored))


def _decide(db: Database, run: LiveRun, pair: Pair, cutoff_ms: int) -> None:
    reader = Reader(db.conn, cutoff_ms)
    held = _held_position(db, run.id, pair.id)
    may_open = cutoff_ms != run.last_instant_ms and not _has_uncovered_leg(db, run.id, pair.id)
    outcome = _plan(db, reader, run.rule, pair, held, cutoff_ms, may_open)
    _record(db, run, pair.id, cutoff_ms, held, outcome, reader.data_until_ms)


def _has_uncovered_leg(db: Database, run_id: int, pair_id: int) -> bool:
    return (
        db.conn.execute(
            "SELECT 1 FROM paper_position WHERE run_id = ? AND pair_id = ?"
            " AND status = 'leg_liquidated'",
            (run_id, pair_id),
        ).fetchone()
        is not None
    )


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
    may_open: bool = True,
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
    if not may_open:
        # An open is never made when it could not be managed: at the horizon, or beside a leg
        # still waiting to be closed.
        choice = _without_opening(choice)
    if choice.action == HOLD:
        return Outcome(HOLD, None, spread, [], None)
    try:
        trades = _plan_trades(db, reader, rule, pair, held, choice)
    except NoAction as no_action:
        return Outcome(NO_ACTION, no_action.cause, spread, [], None)
    return Outcome(choice.action, None, spread, trades, choice.side)


def _without_opening(choice: Choice) -> Choice:
    if choice.action == OPEN:
        return Choice(HOLD, None)
    if choice.action == REVERSE:
        return Choice(CLOSE, None)
    return choice


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
    later may have been credited. Each leg is credited only up to its own closing or liquidation.
    """
    positions = db.conn.execute(
        "SELECT id, pair_id, polymarket_side, opened_at FROM paper_position"
        " WHERE run_id = ? AND opened_at < ?",
        (run_id, iso(cutoff_ms)),
    ).fetchall()
    legs = _leg_table(db, run_id)
    reader = Reader(db.conn, cutoff_ms)
    platform_ids = {name: db.platform_id(name) for name in PLATFORMS}
    rows: list[tuple[int, int, str, float, float]] = []
    for position_id, pair_id, side, opened_at in positions:
        if pair_id in blocked:
            continue
        pair = pairs[pair_id]
        instruments = {
            POLYMARKET: pair.polymarket_instrument_id,
            HYPERLIQUID: pair.hyperliquid_instrument_id,
        }
        for platform, instrument_id in instruments.items():
            quantity, end_ms = legs[position_id, platform]
            pays_when_rate_positive = (side == LONG) == (platform == POLYMARKET)
            payments = reader.payments(
                instrument_id,
                from_iso(opened_at),
                cutoff_ms if end_ms is None else end_ms,
                uncredited_for=(position_id, platform_ids[platform]),
            )
            for source_ms, rate in payments:
                prices = reader.payment_prices(instrument_id, source_ms)
                if prices is None:
                    continue
                price = prices.index if platform == HYPERLIQUID else prices.mark
                amount = rate * quantity * price
                rows.append(
                    (
                        position_id,
                        platform_ids[platform],
                        iso(source_ms),
                        rate,
                        round_money(-amount if pays_when_rate_positive else amount),
                    )
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


def _leg_table(db: Database, run_id: int) -> dict[tuple[int, str], tuple[float, int | None]]:
    """Quantity and end instant (closing or liquidation trade, else None) per position leg."""
    rows = db.conn.execute(
        "SELECT t.position_id, p.name, t.kind, t.hour, t.quantity FROM paper_trade t"
        " JOIN paper_position pos ON pos.id = t.position_id"
        " JOIN platform p ON p.id = t.platform_id WHERE pos.run_id = ? ORDER BY t.id",
        (run_id,),
    ).fetchall()
    table: dict[tuple[int, str], tuple[float, int | None]] = {}
    for position_id, platform, kind, hour, quantity in rows:
        key = (position_id, platform)
        table[key] = (float(quantity), None) if kind == "open" else (table[key][0], from_iso(hour))
    return table


def _active_positions(db: Database, run_id: int) -> list[ActivePosition]:
    rows = db.conn.execute(
        "SELECT id, pair_id, polymarket_side, notional_per_leg, leverage, opened_at, status"
        " FROM paper_position WHERE run_id = ? AND status IN ('open', 'leg_liquidated')"
        " ORDER BY id",
        (run_id,),
    ).fetchall()
    return [
        ActivePosition(r[0], r[1], r[2], float(r[3]), float(r[4]), from_iso(r[5]), r[6])
        for r in rows
    ]


def _alive_legs(db: Database, position: ActivePosition, pair: Pair) -> list[Leg]:
    ended = {
        row[0]
        for row in db.conn.execute(
            "SELECT p.name FROM paper_trade t JOIN platform p ON p.id = t.platform_id"
            " WHERE t.position_id = ? AND t.kind IN ('close', 'liquidation')",
            (position.id,),
        )
    }
    rows = db.conn.execute(
        "SELECT p.name, t.avg_price, t.quantity FROM paper_trade t"
        " JOIN platform p ON p.id = t.platform_id WHERE t.position_id = ? AND t.kind = 'open'"
        " ORDER BY t.id",
        (position.id,),
    ).fetchall()
    instruments = {
        POLYMARKET: pair.polymarket_instrument_id,
        HYPERLIQUID: pair.hyperliquid_instrument_id,
    }
    return [
        Leg(
            name,
            instruments[name],
            (position.side == LONG) == (name == POLYMARKET),
            float(entry),
            float(quantity),
        )
        for name, entry, quantity in rows
        if name not in ended
    ]


def _measure(
    db: Database,
    run: LiveRun,
    pairs: dict[int, Pair],
    cutoff_ms: int,
    blocked: set[int],
    summary: EvaluationSummary,
) -> None:
    """Measure and liquidate every minute that ended before the cutoff, for each open position."""
    for position in _active_positions(db, run.id):
        if position.pair_id in blocked:
            continue
        try:
            _measure_position(db, run, position, pairs[position.pair_id], cutoff_ms)
        except sqlite3.OperationalError as error:
            _defer(error, f"position {position.id} measurement at {iso(cutoff_ms)}", summary)
            blocked.add(position.pair_id)


def _measure_position(
    db: Database,
    run: LiveRun,
    position: ActivePosition,
    pair: Pair,
    cutoff_ms: int,
    close_from_ms: int | None = None,
) -> None:
    last_minute = cutoff_ms - MINUTE_MS
    latest = db.conn.execute(
        "SELECT max(minute) FROM position_measurement WHERE position_id = ?", (position.id,)
    ).fetchone()[0]
    cursor = (
        max(position.opened_ms, run.measured_from_ms)
        if latest is None
        else from_iso(latest) + MINUTE_MS
    )
    while cursor <= last_minute:
        chunk_end = min(cursor + HOUR_MS - MINUTE_MS, last_minute)
        if not _measure_chunk(db, run, position, pair, cursor, chunk_end, close_from_ms):
            return
        cursor = chunk_end + MINUTE_MS


def _margin_at(versions: list[tuple[int, float]], minute_ms: int) -> float | None:
    index = bisect_right([effective for effective, _ in versions], minute_ms) - 1
    return None if index < 0 else versions[index][1]


def _measure_chunk(
    db: Database,
    run: LiveRun,
    position: ActivePosition,
    pair: Pair,
    first_ms: int,
    last_ms: int,
    close_from_ms: int | None = None,
) -> bool:
    """Measure `[first_ms, last_ms]` in one transaction; False once the position has closed."""
    reader = Reader(db.conn, last_ms + MINUTE_MS)
    legs = _alive_legs(db, position, pair)
    prices = {
        POLYMARKET: reader.prices(pair.polymarket_instrument_id, first_ms, last_ms),
        HYPERLIQUID: reader.prices(pair.hyperliquid_instrument_id, first_ms, last_ms),
    }
    margins = {leg.platform: reader.maintenance_margins(leg.instrument_id) for leg in legs}
    baseline = db.conn.execute(
        "SELECT basis FROM position_measurement WHERE position_id = ? AND basis IS NOT NULL"
        " ORDER BY minute LIMIT 1",
        (position.id,),
    ).fetchone()
    base_basis: float | None = None if baseline is None else float(baseline[0])
    loss = round_money(position.notional / position.leverage)
    status = position.status
    closed_at: str | None = None
    measurements: list[tuple[int, str, float | None, float | None, float | None, float | None]] = []
    liquidations: list[tuple[Leg, float, str]] = []
    closes: list[tuple[str, list[PlannedTrade]]] = []
    for minute in range(first_ms, last_ms + 1, MINUTE_MS):
        pm_price, hl_price = prices[POLYMARKET].get(minute), prices[HYPERLIQUID].get(minute)
        basis = None if pm_price is None or hl_price is None else pm_price.mark - hl_price.mark
        if basis is not None and base_basis is None:
            base_basis = basis
        distances: dict[str, float | None] = {POLYMARKET: None, HYPERLIQUID: None}
        crossed: list[tuple[Leg, float]] = []
        for leg in legs:
            price = prices[leg.platform].get(minute)
            margin = _margin_at(margins[leg.platform], minute)
            if price is None or margin is None:
                continue
            level = liquidation_price(leg.is_long, leg.entry, position.leverage, margin)
            distances[leg.platform] = liquidation_distance(leg.is_long, price.mark, level)
            if is_liquidated(leg.is_long, price.mark, level):
                crossed.append((leg, level))
        measurements.append(
            (
                position.id,
                iso(minute),
                basis,
                None if basis is None or base_basis is None else basis - base_basis,
                distances[POLYMARKET],
                distances[HYPERLIQUID],
            )
        )
        for leg, level in crossed:
            liquidations.append((leg, level, iso(minute)))
            legs = [other for other in legs if other is not leg]
            status = "leg_liquidated"
        closing_everything = close_from_ms is not None and minute >= close_from_ms
        if legs and (status == "leg_liquidated" or closing_everything):
            try:
                planned = _plan_leg_closes(
                    Reader(db.conn, minute + MINUTE_MS),
                    run.rule,
                    pair,
                    position.side,
                    {leg.platform: leg.quantity for leg in legs},
                )
            except NoAction:
                pass
            else:
                closes.append((iso(minute), planned))
                legs = []
        if not legs:
            status, closed_at = "closed", iso(minute)
            break
    platform_ids = {name: db.platform_id(name) for name in PLATFORMS}
    with db.conn:
        db.conn.executemany(
            "INSERT INTO position_measurement VALUES (?, ?, ?, ?, ?, ?)", measurements
        )
        for leg, level, hour in liquidations:
            db.conn.execute(
                "INSERT INTO paper_trade (position_id, platform_id, kind, hour, side, avg_price,"
                " best_price, quantity, fee, slippage, snapshot_minute, loss)"
                " VALUES (?, ?, 'liquidation', ?, ?, ?, ?, ?, 0, 0, ?, ?)",
                (
                    position.id,
                    platform_ids[leg.platform],
                    hour,
                    "sell" if leg.is_long else "buy",
                    level,
                    level,
                    leg.quantity,
                    hour,
                    loss,
                ),
            )
        for hour, planned in closes:
            _insert_trades(db, position.id, hour, planned, platform_ids)
        if status != position.status:
            db.conn.execute(
                "UPDATE paper_position SET status = ?, closed_at = ? WHERE id = ?",
                (status, closed_at, position.id),
            )
    return status != "closed"


def _plan_leg_closes(
    reader: Reader,
    rule: Preregistration,
    pair: Pair,
    side: str,
    quantities: dict[str, float],
) -> list[PlannedTrade]:
    """Close the given legs by walking each one's usable snapshot with its taker fee."""
    trades: list[PlannedTrade] = []
    for platform, quantity in quantities.items():
        instrument_id = (
            pair.polymarket_instrument_id
            if platform == POLYMARKET
            else pair.hyperliquid_instrument_id
        )
        snapshot = reader.snapshot(instrument_id, rule.snapshot_max_age_s * 1000)
        if snapshot is None:
            raise NoAction(NO_USABLE_SNAPSHOT)
        taker = reader.taker_fee(platform, FEE_CATEGORY[platform])
        if taker is None:
            raise NoAction(MISSING_FEE)
        trades.append(_trade(platform, "close", side, snapshot, taker, quantity=quantity))
    return trades


def _close_at_horizon(
    db: Database, run: LiveRun, pairs: dict[int, Pair], now_ms: int, summary: EvaluationSummary
) -> None:
    """Close what is open at the last instant, else retry minute by minute to the horizon end."""
    instant = run.last_instant_ms
    platform_ids = {name: db.platform_id(name) for name in PLATFORMS}
    blocked: set[int] = set()
    for position in _active_positions(db, run.id):
        pair = pairs[position.pair_id]
        try:
            _measure_position(db, run, position, pair, instant)
            if _is_closed(db, position.id):
                continue
            planned = _plan_leg_closes(
                Reader(db.conn, instant),
                run.rule,
                pair,
                position.side,
                {leg.platform: leg.quantity for leg in _alive_legs(db, position, pair)},
            )
            with db.conn:
                _insert_trades(db, position.id, iso(instant), planned, platform_ids)
                db.conn.execute(
                    "UPDATE paper_position SET status = 'closed', closed_at = ? WHERE id = ?",
                    (iso(instant), position.id),
                )
        except NoAction:
            if now_ms >= run.horizon_end_ms and not _retry_horizon_close(
                db, run, position, pair, summary
            ):
                blocked.add(position.pair_id)
        except sqlite3.OperationalError as error:
            _defer(error, f"position {position.id} horizon close", summary)
            # The next run may close this leg at the last instant, after which nothing later
            # may have been credited.
            blocked.add(position.pair_id)
    if now_ms >= run.horizon_end_ms:
        # Legs that stayed open past the last instant are owed the payments until they end.
        _accrue(db, run.id, pairs, run.horizon_end_ms, blocked, summary)


def _retry_horizon_close(
    db: Database, run: LiveRun, position: ActivePosition, pair: Pair, summary: EvaluationSummary
) -> bool:
    """Retry minute by minute; False when a lock deferred it."""
    try:
        _measure_position(
            db, run, position, pair, run.horizon_end_ms, close_from_ms=run.last_instant_ms
        )
    except sqlite3.OperationalError as error:
        _defer(error, f"position {position.id} horizon close", summary)
        return False
    return True


def _is_closed(db: Database, position_id: int) -> bool:
    row = db.conn.execute(
        "SELECT status FROM paper_position WHERE id = ?", (position_id,)
    ).fetchone()
    return bool(row[0] == "closed")


def reevaluate(db: Database, variant_number: int, now_ms: int) -> Reevaluation:
    """Decide a variant's live period again over the stored data, as a run of its own."""
    add_missing_columns(db.conn)
    variants = db.conn.execute(
        "SELECT id, preregistration FROM variant WHERE number = ? ORDER BY id", (variant_number,)
    ).fetchall()
    if not variants:
        raise ReevaluationError(f"no variant {variant_number}")
    if len(variants) > 1:
        raise ReevaluationError(f"variant number {variant_number} belongs to several methods")
    variant_id, text = variants[0]
    live = db.conn.execute(
        "SELECT starts_at FROM run WHERE variant_id = ? AND mode = 'live' ORDER BY id LIMIT 1",
        (variant_id,),
    ).fetchone()
    if live is None:
        raise ReevaluationError(f"variant {variant_number} has no live run to re-evaluate")
    with db.conn:
        cursor = db.conn.execute(
            "INSERT INTO run (variant_id, mode, starts_at, status, measured_from)"
            " VALUES (?, 'reevaluation', ?, 'in_progress', ?)",
            (variant_id, live[0], live[0]),
        )
    assert cursor.lastrowid is not None
    run = LiveRun(cursor.lastrowid, from_iso(live[0]), parse_preregistration(text), REEVALUATION)
    summary = EvaluationSummary()
    _evaluate_run(db, run, _load_pairs(db), now_ms, summary)
    status = db.conn.execute("SELECT status FROM run WHERE id = ?", (run.id,)).fetchone()[0]
    return Reevaluation(run.id, status, summary)
