from pathlib import Path

import pytest

from polyquack.cli import main
from polyquack.completeness import render_completeness
from polyquack.ingestion.platforms import HYPERLIQUID, POLYMARKET
from polyquack.storage.db import Database
from polyquack.times import HOUR_MS, MINUTE_MS, floor_to, iso

from .conftest import T0, seed_pairs

HOUR = floor_to(T0, HOUR_MS)
NOW = HOUR + 30 * MINUTE_MS
FIRST = HOUR - 3 * HOUR_MS


def _fill(db: Database, instrument_id: int, funding_hours: list[int], every_minutes: int) -> None:
    for hour in funding_hours:
        db.insert_funding(instrument_id, hour + 40, 0.0000125, hour + MINUTE_MS)
    with db.conn:
        db.conn.executemany(
            "INSERT INTO book_snapshot VALUES (?, ?, 't', 1, 2, 1, 1, '[]', '[]', 0.1, 0.1)",
            [(instrument_id, iso(FIRST + m * MINUTE_MS)) for m in range(0, 180, every_minutes)],
        )


def test_report_counts_hours_with_funding_and_minutes_with_a_snapshot_per_pair_and_platform(
    db: Database,
) -> None:
    seed_pairs(db, ["AAA", "BBB"])
    complete = [FIRST + n * HOUR_MS for n in range(3)]
    for target in db.targets():
        if target.asset == "AAA":
            _fill(db, target.instrument_id, complete, 1)
        else:
            _fill(db, target.instrument_id, complete[:1] + complete[2:], 2)

    text = render_completeness(db, (), 1, NOW)

    lines = {tuple(line.split()[:2]): line for line in text.splitlines()[1:]}
    assert "funding 3/3 100.0%" in lines[("AAA", POLYMARKET)]
    assert "book 180/180 100.0%" in lines[("AAA", HYPERLIQUID)]
    assert "funding 2/3 66.7%" in lines[("BBB", POLYMARKET)]
    assert "book 90/180 50.0%" in lines[("BBB", HYPERLIQUID)]


def test_a_gap_starts_the_expectation_of_its_kind(db: Database) -> None:
    seed_pairs(db, ["AAA"])
    target = db.targets()[0]
    db.insert_gap(
        target.platform, target.instrument_id, "funding", FIRST, FIRST + HOUR_MS, "x", "open"
    )
    db.insert_funding(target.instrument_id, FIRST + HOUR_MS + 40, 0.1, NOW)

    text = render_completeness(db, ("AAA",), 1, NOW)

    assert "funding 1/3 33.3%" in text.splitlines()[1]


def test_an_instrument_without_readings_or_gaps_has_nothing_expected(db: Database) -> None:
    seed_pairs(db, ["AAA"])

    text = render_completeness(db, (), 7, NOW)

    assert "funding n/a  book n/a" in text


def test_completeness_command_reads_the_database_and_takes_a_window(
    db: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_pairs(db, ["AAA"])
    _fill(db, db.targets()[0].instrument_id, [FIRST], 1)
    monkeypatch.setenv("POLYQUACK_DB", str(tmp_path / "test.db"))

    assert main(["completeness", "--days", "3"]) == 0

    assert "AAA" in capsys.readouterr().out
