from polyquack.storage.db import Database, Target
from polyquack.times import HOUR_MS, MINUTE_MS, floor_to, from_iso, iso

DAY_MS = 24 * HOUR_MS


def render_completeness(db: Database, assets: tuple[str, ...], days: int, now_ms: int) -> str:
    end = floor_to(now_ms, HOUR_MS)
    start = end - days * DAY_MS
    lines = [f"Completeness from {iso(start)} to {iso(end)}"]
    for target in db.targets(assets, include_delisted=True):
        funding = _funding(db, target, start, end)
        book = _book(db, target, start, end)
        lines.append(f"{target.asset:<10} {target.platform:<17} funding {funding}  book {book}")
    return "\n".join(lines)


def _share(got: int, expected: int) -> str:
    return "n/a" if expected <= 0 else f"{got}/{expected} {100 * got / expected:.1f}%"


def _first_interval(db: Database, target: Target, kind: str) -> int | None:
    """Start of the first interval of this kind holding a reading or a gap."""
    table, column = (
        ("funding_reading", "source_time") if kind == "funding" else ("book_snapshot", "minute")
    )
    reading = db.conn.execute(
        f"SELECT min({column}) FROM {table} WHERE instrument_id = ?", (target.instrument_id,)
    ).fetchone()[0]
    gap = db.conn.execute(
        "SELECT min(starts_at) FROM gap WHERE instrument_id = ? AND kind = ?",
        (target.instrument_id, kind),
    ).fetchone()[0]
    step = HOUR_MS if kind == "funding" else MINUTE_MS
    starts = []
    if reading is not None:
        starts.append(floor_to(from_iso(reading) + step // 2, step))
    if gap is not None:
        starts.append(from_iso(gap))
    return min(starts) if starts else None


def _funding(db: Database, target: Target, start: int, end: int) -> str:
    first = _first_interval(db, target, "funding")
    if first is None:
        return "n/a"
    first = max(first, start)
    rows = db.conn.execute(
        "SELECT source_time FROM funding_reading WHERE instrument_id = ?"
        " AND source_time >= ? AND source_time < ?",
        (target.instrument_id, iso(first - HOUR_MS // 2), iso(end - HOUR_MS // 2)),
    ).fetchall()
    hours = {floor_to(from_iso(row[0]) + HOUR_MS // 2, HOUR_MS) for row in rows}
    return _share(len(hours), (end - first) // HOUR_MS)


def _book(db: Database, target: Target, start: int, end: int) -> str:
    first = _first_interval(db, target, "book_snapshot")
    if first is None:
        return "n/a"
    first = max(first, start)
    got = db.conn.execute(
        "SELECT count(*) FROM book_snapshot WHERE instrument_id = ? AND minute >= ? AND minute < ?",
        (target.instrument_id, iso(first), iso(end)),
    ).fetchone()[0]
    return _share(got, (end - first) // MINUTE_MS)
