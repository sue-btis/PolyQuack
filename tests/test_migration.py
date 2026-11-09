import sqlite3
from pathlib import Path

import pytest

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
