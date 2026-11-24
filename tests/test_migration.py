import sqlite3
from pathlib import Path
from typing import Any

import pytest

from polyquack.evaluation.runner import evaluate
from polyquack.storage.db import Database, MigrationError

M01_FEE_SCHEDULE = """
CREATE TABLE platform (id integer PRIMARY KEY, name text NOT NULL UNIQUE);
CREATE TABLE fee_schedule (
    platform_id integer NOT NULL REFERENCES platform (id),
    effective_from text NOT NULL,
    tier text NOT NULL,
    taker real NOT NULL,
    maker real NOT NULL,
    PRIMARY KEY (platform_id, effective_from, tier)
);
"""


def _m01_database(path: Path, with_row: bool) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(M01_FEE_SCHEDULE)
    if with_row:
        conn.execute("INSERT INTO platform (name) VALUES ('hyperliquid')")
        conn.execute("INSERT INTO fee_schedule VALUES (1, 't', '0', 0.1, 0.1)")
    conn.commit()
    conn.close()


def test_an_empty_m01_fee_schedule_is_recreated_with_category_and_the_new_key(
    tmp_path: Path,
) -> None:
    _m01_database(tmp_path / "m01.db", with_row=False)

    db = Database(tmp_path / "m01.db")

    columns = [row[1] for row in db.conn.execute("PRAGMA table_info(fee_schedule)")]
    key = [row[1] for row in db.conn.execute("PRAGMA table_info(fee_schedule)") if row[5]]
    assert "category" in columns
    assert key == ["platform_id", "effective_from", "category", "tier"]


def test_a_non_empty_m01_fee_schedule_refuses_to_start(tmp_path: Path) -> None:
    _m01_database(tmp_path / "m01.db", with_row=True)

    with pytest.raises(MigrationError, match="fee_schedule"):
        Database(tmp_path / "m01.db")

    rows = sqlite3.connect(tmp_path / "m01.db").execute("SELECT count(*) FROM fee_schedule")
    assert rows.fetchone()[0] == 1


def test_a_migrated_database_starts_again_without_changes(tmp_path: Path) -> None:
    _m01_database(tmp_path / "m01.db", with_row=False)
    Database(tmp_path / "m01.db").close()

    Database(tmp_path / "m01.db").close()


M03_EVALUATION_TABLES = """
CREATE TABLE platform (id integer PRIMARY KEY, name text NOT NULL UNIQUE);
CREATE TABLE run (
    id integer PRIMARY KEY, variant_id integer NOT NULL, mode text NOT NULL,
    starts_at text NOT NULL, ends_at text, status text NOT NULL, reason text
);
CREATE TABLE paper_position (
    id integer PRIMARY KEY, run_id integer NOT NULL, pair_id integer NOT NULL,
    polymarket_side text NOT NULL, notional_per_leg real NOT NULL, leverage real NOT NULL,
    opened_at text NOT NULL, closed_at text, status text NOT NULL
);
CREATE TABLE paper_trade (
    id integer PRIMARY KEY,
    position_id integer NOT NULL REFERENCES paper_position (id),
    platform_id integer NOT NULL REFERENCES platform (id),
    kind text NOT NULL, hour text NOT NULL, side text NOT NULL, avg_price real NOT NULL,
    best_price real NOT NULL, quantity real NOT NULL, fee real NOT NULL, slippage real NOT NULL,
    snapshot_minute text NOT NULL
);
"""


def _m03_database(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(M03_EVALUATION_TABLES)
    conn.execute("INSERT INTO platform (name) VALUES ('hyperliquid')")
    conn.execute("INSERT INTO run VALUES (1, 1, 'live', 's', NULL, 'in_progress', NULL)")
    conn.execute("INSERT INTO paper_position VALUES (1, 1, 1, 'long', 1000, 2, 'a', NULL, 'open')")
    conn.execute(
        "INSERT INTO paper_trade VALUES (1, 1, 1, 'open', 'h', 'buy', 1, 1, 10, 0.4, 0, 's')"
    )
    conn.commit()
    conn.close()


def test_m04_an_m03_database_keeps_its_trades_and_gains_the_loss_column_once(
    tmp_path: Path,
) -> None:
    _m03_database(tmp_path / "m03.db")
    db = Database(tmp_path / "m03.db")

    evaluate(db, 0)
    evaluate(db, 0)

    columns = [row[1] for row in db.conn.execute("PRAGMA table_info(paper_trade)")]
    assert columns.count("loss") == 1
    assert db.conn.execute("SELECT id, fee, loss FROM paper_trade").fetchall() == [(1, 0.4, None)]
    tables = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"position_measurement", "excluded_pair", "verdict"} <= tables


def test_m04_a_fresh_database_has_the_loss_column_and_nullable_verdict_columns(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "fresh.db")

    evaluate(db, 0)

    def column(table: str, name: str) -> tuple[Any, ...]:
        return next(r for r in db.conn.execute(f"PRAGMA table_info({table})") if r[1] == name)

    assert column("paper_trade", "loss")[3] == 0
    assert column("verdict", "annual_return_on_collateral")[3] == 0
    assert column("verdict", "reason")[3] == 0


def test_m04_an_m03_run_gains_the_measured_from_column_once_and_keeps_its_row(
    tmp_path: Path,
) -> None:
    _m03_database(tmp_path / "m03.db")
    db = Database(tmp_path / "m03.db")

    evaluate(db, 0)
    evaluate(db, 0)

    columns = [row[1] for row in db.conn.execute("PRAGMA table_info(run)")]
    assert columns.count("measured_from") == 1
    assert db.conn.execute("SELECT id, mode, status, measured_from FROM run").fetchall() == [
        (1, "live", "in_progress", None)
    ]
