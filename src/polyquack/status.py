from polyquack.storage.db import Database, Target
from polyquack.times import HOUR_MS, iso

DAY_MS = 24 * HOUR_MS


def render_status(db: Database, assets: tuple[str, ...], now_ms: int) -> str:
    lines = [f"Status at {iso(now_ms)}"]
    targets = db.targets(assets)
    for asset in assets:
        lines.append(f"\nPair {asset}")
        asset_targets = [t for t in targets if t.asset == asset]
        if not asset_targets:
            lines.append("  not paired")
        for target in asset_targets:
            lines += _target_lines(db, target, now_ms)
    unpaired = db.unpaired_instruments()
    lines.append(f"\nUnpaired instruments: {len(unpaired)}")
    for platform in dict.fromkeys(p for p, _ in unpaired):
        symbols = ", ".join(s for p, s in unpaired if p == platform)
        lines.append(f"  {platform}: {symbols}")
    return "\n".join(lines)


def _target_lines(db: Database, target: Target, now_ms: int) -> list[str]:
    conn = db.conn
    funding = conn.execute(
        "SELECT source_time, rate, received_at FROM funding_reading WHERE instrument_id = ?"
        " ORDER BY source_time DESC LIMIT 1",
        (target.instrument_id,),
    ).fetchone()
    book = conn.execute(
        "SELECT minute, best_bid, best_ask, bid_reach, ask_reach FROM book_snapshot"
        " WHERE instrument_id = ? ORDER BY minute DESC LIMIT 1",
        (target.instrument_id,),
    ).fetchone()
    price = conn.execute(
        "SELECT minute, mark_price, index_price, source_time FROM price_reading"
        " WHERE instrument_id = ? ORDER BY minute DESC LIMIT 1",
        (target.instrument_id,),
    ).fetchone()
    lines = [f"  {target.platform} (instrument {target.instrument_id})"]
    lines.append(
        "    funding: none"
        if funding is None
        else f"    funding: {funding[0]} rate={funding[1]} received={funding[2]}"
    )
    lines.append(
        "    book:    none"
        if book is None
        else f"    book:    {book[0]} bid={book[1]} ask={book[2]} reach={book[3]:.5f}/{book[4]:.5f}"
    )
    lines.append(
        "    price:   none"
        if price is None
        else f"    price:   {price[0]} mark={price[1]} index={price[2]} source_time={price[3]}"
    )
    lines += _gap_lines(db, target, now_ms)
    return lines


def _gap_lines(db: Database, target: Target, now_ms: int) -> list[str]:
    rows = db.conn.execute(
        "SELECT kind, starts_at, ends_at, cause, status FROM gap"
        " WHERE instrument_id = ? AND starts_at >= ? ORDER BY kind, starts_at",
        (target.instrument_id, iso(now_ms - DAY_MS)),
    ).fetchall()
    merged: list[list[object]] = []
    for kind, starts, ends, cause, status in rows:
        last = merged[-1] if merged else None
        if last and last[0] == kind and last[2] == starts and last[3] == cause:
            last[2] = ends
            last[5] = int(str(last[5])) + 1
        else:
            merged.append([kind, starts, ends, cause, status, 1])
    lines = [f"    gaps in the last 24 h: {sum(int(str(m[5])) for m in merged)} interval(s)"]
    lines += [
        f"      {kind} {starts} -> {ends} cause={cause} status={status} ({count})"
        for kind, starts, ends, cause, status, count in merged
    ]
    return lines
