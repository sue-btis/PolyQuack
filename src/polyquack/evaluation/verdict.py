import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from polyquack.evaluation.money import round_money
from polyquack.evaluation.preregistration import Preregistration
from polyquack.evaluation.readings import Reader
from polyquack.ingestion.platforms import HYPERLIQUID, POLYMARKET
from polyquack.storage.db import Database
from polyquack.times import HOUR_MS, MINUTE_MS, from_iso, iso

CONTINUE = "continue"
DISCARD = "discard"
INVESTIGATE_FURTHER = "investigate_further"
NO_POSITIONS = "no positions"

MAX_HOURS_WITHOUT_FUNDING_PERCENT = 5
MAX_MINUTES_WITHOUT_SNAPSHOT_PERCENT = 10
AMOUNT_FIELDS = ("funding", "fees", "slippage", "basis", "liquidations")


def annual_return(net: float, collateral: float, horizon_days: int) -> float:
    return net / collateral * 365 / horizon_days


def outcome_for(annual: float, minimum: float) -> str:
    return CONTINUE if annual >= minimum else DISCARD


def max_collateral(positions: Sequence[tuple[int, int | None, float]]) -> float:
    """Peak of the amounts committed at once; each is `(opened_ms, closed_ms or None, amount)`.

    Closing sorts before opening at the same instant so a reversal does not count twice; a
    position that opens and closes at the same instant still commits its amount at that instant.
    """
    events: list[tuple[int, int, float]] = []
    for opened_ms, closed_ms, amount in positions:
        if closed_ms == opened_ms:
            events.append((opened_ms, 2, amount))
            continue
        events.append((opened_ms, 1, amount))
        if closed_ms is not None:
            events.append((closed_ms, 0, -amount))
    committed = peak = 0.0
    for _, kind, change in sorted(events):
        if kind == 2:
            peak = max(peak, committed + change)
            continue
        committed += change
        peak = max(peak, committed)
    return peak


def limits_exceeded(
    expected_hours: int, hours_without_funding: int, expected_minutes: int, minutes_without: int
) -> str | None:
    """Why a pair is excluded, or None; integer arithmetic keeps the strict limits exact."""
    reasons = []
    if hours_without_funding * 100 > expected_hours * MAX_HOURS_WITHOUT_FUNDING_PERCENT:
        reasons.append(
            f"{hours_without_funding} of {expected_hours} hours without funding exceed"
            f" {MAX_HOURS_WITHOUT_FUNDING_PERCENT}%"
        )
    if minutes_without * 100 > expected_minutes * MAX_MINUTES_WITHOUT_SNAPSHOT_PERCENT:
        reasons.append(
            f"{minutes_without} of {expected_minutes} minutes without snapshot exceed"
            f" {MAX_MINUTES_WITHOUT_SNAPSHOT_PERCENT}%"
        )
    return "; ".join(reasons) or None


class PairLike(Protocol):
    @property
    def id(self) -> int: ...
    @property
    def polymarket_instrument_id(self) -> int: ...
    @property
    def hyperliquid_instrument_id(self) -> int: ...
    @property
    def paired_ms(self) -> int: ...
    @property
    def symbol(self) -> str: ...


class RunLike(Protocol):
    @property
    def id(self) -> int: ...
    @property
    def starts_ms(self) -> int: ...
    @property
    def rule(self) -> Preregistration: ...
    @property
    def horizon_end_ms(self) -> int: ...
    @property
    def last_instant_ms(self) -> int: ...


@dataclass(frozen=True)
class Exclusion:
    pair_id: int
    expected_hours: int
    hours_without_funding: int
    expected_minutes: int
    minutes_without_snapshot: int
    reason: str


@dataclass
class Amounts:
    funding: float = 0.0
    fees: float = 0.0
    slippage: float = 0.0
    basis: float = 0.0
    liquidations: float = 0.0
    uncredited_payments: int = 0
    unclosed_positions: int = 0

    def add(self, other: "Amounts") -> None:
        for name in AMOUNT_FIELDS:
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.uncredited_payments += other.uncredited_payments
        self.unclosed_positions += other.unclosed_positions

    def net(self) -> float:
        return round_money(
            self.funding - self.fees - self.slippage + self.basis - self.liquidations
        )

    def rounded(self) -> dict[str, float | int]:
        return {
            **{name: round_money(getattr(self, name)) for name in AMOUNT_FIELDS},
            "net": self.net(),
            "uncredited_payments": self.uncredited_payments,
            "unclosed_positions": self.unclosed_positions,
        }


def _ceil_to(ms: int, step_ms: int) -> int:
    return -(-ms // step_ms) * step_ms


def _period(reader: Reader, run: RunLike, pair: PairLike) -> range:
    """The pair's expected period in ms; empty when it was paired after, or delisted before, it."""
    instruments = (pair.polymarket_instrument_id, pair.hyperliquid_instrument_id)
    delistings = [
        moment for i in instruments if (moment := reader.delisted_since_ms(i)) is not None
    ]
    return range(max(pair.paired_ms, run.starts_ms), min([run.horizon_end_ms, *delistings]))


def _exclusion(reader: Reader, run: RunLike, pair: PairLike) -> Exclusion | None:
    instruments = (pair.polymarket_instrument_id, pair.hyperliquid_instrument_id)
    period = _period(reader, run, pair)
    start, end = period.start, period.stop
    hours = range(_ceil_to(start, HOUR_MS), end, HOUR_MS)
    minutes = range(_ceil_to(start, MINUTE_MS), end, MINUTE_MS)
    funded, snapshotted = set(hours), set(minutes)
    if hours:
        for instrument_id in instruments:
            funded &= reader.funding_by_hour(instrument_id, hours[0], hours[-1]).keys()
    if minutes:
        for instrument_id in instruments:
            snapshotted &= reader.snapshot_minutes(instrument_id, minutes[0], end)
    without_funding, without_snapshot = len(hours) - len(funded), len(minutes) - len(snapshotted)
    reason = limits_exceeded(len(hours), without_funding, len(minutes), without_snapshot)
    if reason is None:
        return None
    return Exclusion(pair.id, len(hours), without_funding, len(minutes), without_snapshot, reason)


def _position_amounts(
    db: Database, reader: Reader, run: RunLike, pair: PairLike, position_id: int, side: str
) -> Amounts:
    amounts = Amounts()
    trades = db.conn.execute(
        "SELECT p.name, t.kind, t.best_price, t.quantity, t.fee, t.slippage, t.loss, t.hour"
        " FROM paper_trade t JOIN platform p ON p.id = t.platform_id WHERE t.position_id = ?"
        " ORDER BY t.id",
        (position_id,),
    ).fetchall()
    entries: dict[str, tuple[float, float]] = {}
    ends: dict[str, int] = {}
    for platform, kind, best, quantity, fee, slippage, loss, hour in trades:
        amounts.fees += fee
        amounts.slippage += slippage
        if kind == "open":
            entries[platform] = (best, quantity)
            continue
        ends[platform] = from_iso(hour)
        if kind == "liquidation":
            amounts.liquidations += loss
        else:
            entry, entry_quantity = entries[platform]
            is_long = (side == "long") == (platform == POLYMARKET)
            amounts.basis += (best - entry) * entry_quantity * (1 if is_long else -1)
    amounts.unclosed_positions = int(len(ends) < len(entries))
    row = db.conn.execute(
        "SELECT opened_at, (SELECT COALESCE(sum(amount), 0) FROM paper_funding_payment"
        " WHERE position_id = paper_position.id) FROM paper_position WHERE id = ?",
        (position_id,),
    ).fetchone()
    opened, amounts.funding = from_iso(row[0]), float(row[1])
    instruments = {
        POLYMARKET: pair.polymarket_instrument_id,
        HYPERLIQUID: pair.hyperliquid_instrument_id,
    }
    for platform, instrument_id in instruments.items():
        due = reader.payments(instrument_id, opened, ends.get(platform, run.horizon_end_ms))
        credited = db.conn.execute(
            "SELECT count(*) FROM paper_funding_payment f JOIN platform p ON p.id = f.platform_id"
            " WHERE f.position_id = ? AND p.name = ?",
            (position_id, platform),
        ).fetchone()[0]
        amounts.uncredited_payments += len(due) - credited
    return amounts


def finish_run(
    db: Database, run: RunLike, pairs: Sequence[PairLike], now_ms: int, issue_verdict: bool
) -> None:
    """Exclude pairs, total the run and complete it; a re-evaluation also gets its verdict."""
    reader = Reader(db.conn, run.horizon_end_ms)
    pairs = [pair for pair in pairs if _period(reader, run, pair)]
    exclusions = [found for pair in pairs if (found := _exclusion(reader, run, pair)) is not None]
    excluded_ids = {found.pair_id for found in exclusions}
    kept = [pair for pair in pairs if pair.id not in excluded_ids]
    status, reason = "complete", None
    if pairs and not kept:
        status, reason = "not_qualifiable", "every pair was excluded for gaps beyond the limits"
    by_pair: dict[str, Amounts] = {}
    commitments: list[tuple[int, int | None, float]] = []
    for pair in kept:
        rows = db.conn.execute(
            "SELECT id, polymarket_side, notional_per_leg, leverage, opened_at, closed_at"
            " FROM paper_position WHERE run_id = ? AND pair_id = ? ORDER BY opened_at, id",
            (run.id, pair.id),
        ).fetchall()
        for position_id, side, notional, leverage, opened_at, closed_at in rows:
            found_amounts = _position_amounts(db, reader, run, pair, position_id, side)
            by_pair.setdefault(pair.symbol, Amounts()).add(found_amounts)
            commitments.append(
                (
                    from_iso(opened_at),
                    None if closed_at is None else from_iso(closed_at),
                    2 * notional / leverage,
                )
            )
    with db.conn:
        db.conn.executemany(
            "INSERT INTO excluded_pair VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    run.id,
                    e.pair_id,
                    e.expected_hours,
                    e.hours_without_funding,
                    e.expected_minutes,
                    e.minutes_without_snapshot,
                    e.reason,
                )
                for e in exclusions
            ],
        )
        db.conn.execute(
            "UPDATE run SET status = ?, reason = ?, ends_at = ? WHERE id = ?",
            (status, reason, iso(run.horizon_end_ms), run.id),
        )
        if issue_verdict and status == "complete":
            _insert_verdict(db, run, now_ms, by_pair, commitments)


def _insert_verdict(
    db: Database,
    run: RunLike,
    now_ms: int,
    by_pair: dict[str, Amounts],
    commitments: list[tuple[int, int | None, float]],
) -> None:
    total = Amounts()
    for amounts in by_pair.values():
        for name in AMOUNT_FIELDS:
            setattr(total, name, getattr(total, name) + round_money(getattr(amounts, name)))
        total.uncredited_payments += amounts.uncredited_payments
        total.unclosed_positions += amounts.unclosed_positions
    collateral = round_money(max_collateral(commitments))
    annual: float | None = None
    reason: str | None = None
    if not commitments:
        outcome, reason = INVESTIGATE_FURTHER, NO_POSITIONS
    else:
        annual = annual_return(total.net(), collateral, run.rule.horizon_days)
        outcome = outcome_for(annual, run.rule.min_annual_return)
    variants = db.conn.execute(
        "SELECT count(*) FROM variant WHERE first_run_at IS NOT NULL AND method_id ="
        " (SELECT v.method_id FROM variant v JOIN run r ON r.variant_id = v.id WHERE r.id = ?)",
        (run.id,),
    ).fetchone()[0]
    breakdown = {
        **total.rounded(),
        "pairs": {symbol: amounts.rounded() for symbol, amounts in by_pair.items()},
    }
    db.conn.execute(
        "INSERT INTO verdict (run_id, issued_at, outcome, max_collateral,"
        " annual_return_on_collateral, breakdown, variants_tested, reason)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run.id,
            iso(now_ms),
            outcome,
            collateral,
            annual,
            json.dumps(breakdown, sort_keys=True),
            variants,
            reason,
        ),
    )


def render_verdict(db: Database, run_id: int) -> str | None:
    """The run's verdict, breakdown, excluded pairs and variants tested; None if there is no run."""
    run = db.conn.execute(
        "SELECT r.mode, r.status, r.reason, r.starts_at, r.ends_at, v.number, m.name"
        " FROM run r JOIN variant v ON v.id = r.variant_id JOIN method m ON m.id = v.method_id"
        " WHERE r.id = ?",
        (run_id,),
    ).fetchone()
    if run is None:
        return None
    mode, status, run_reason, starts_at, ends_at, number, method = run
    lines = [f"Run {run_id}: {mode} of {method} variant {number}, {status}"]
    lines.append(f"Period: {starts_at} to {ends_at or 'not finished'}")
    if run_reason:
        lines.append(f"Reason: {run_reason}")
    excluded = db.conn.execute(
        "SELECT a.symbol, e.expected_hours, e.hours_without_funding, e.expected_minutes,"
        " e.minutes_without_snapshot, e.reason FROM excluded_pair e"
        " JOIN pair ON pair.id = e.pair_id JOIN asset a ON a.id = pair.asset_id"
        " WHERE e.run_id = ? ORDER BY a.symbol",
        (run_id,),
    ).fetchall()
    verdict = db.conn.execute(
        "SELECT outcome, max_collateral, annual_return_on_collateral, breakdown,"
        " variants_tested, reason, issued_at FROM verdict WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if verdict is None:
        lines.append("No verdict")
    else:
        outcome, collateral, annual, text, variants, reason, issued_at = verdict
        breakdown = json.loads(text)
        lines.append(f"Outcome: {outcome} (issued {issued_at})")
        lines.append(
            "Annual return on collateral: "
            + (f"{annual:.2%}" if annual is not None else f"undefined ({reason})")
        )
        lines.append(f"Maximum collateral: {collateral:.2f} USD")
        lines += [
            f"Net profit: {breakdown['net']:.2f} USD",
            f"  Funding: {breakdown['funding']:.2f}",
            f"  Fees: -{breakdown['fees']:.2f}",
            f"  Slippage: -{breakdown['slippage']:.2f}",
            f"  Basis effect: {breakdown['basis']:.2f}",
            f"  Liquidations: -{breakdown['liquidations']:.2f}",
            f"Uncredited funding payments: {breakdown['uncredited_payments']}",
            f"Positions still open at the horizon: {breakdown['unclosed_positions']}",
        ]
    if not excluded:
        lines.append("Excluded pairs: none")
    else:
        lines.append("Excluded pairs:")
        lines += [
            f"  {symbol}: {no_funding} of {hours} hours without funding,"
            f" {no_snapshot} of {minutes} minutes without snapshot ({why})"
            for symbol, hours, no_funding, minutes, no_snapshot, why in excluded
        ]
    if verdict is not None:
        lines.append(f"Variants tested: {verdict[4]}")
    return "\n".join(lines)
