import sqlite3


def add_missing_columns(conn: sqlite3.Connection) -> None:
    """Bring a database created by the previous evaluation schema up to date, keeping its rows.

    SQLite has no ADD COLUMN IF NOT EXISTS and `CREATE TABLE IF NOT EXISTS` leaves an existing
    table untouched, so a column added to an existing table needs this explicit step.
    """
    for table, column, definition in (
        ("paper_trade", "loss", "real"),
        ("run", "measured_from", "text"),
    ):
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
        if columns and column not in columns:
            with conn:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
