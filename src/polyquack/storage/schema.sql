-- Ingestion tables of docs/design/data/schema.dbml. Datetimes are UTC ISO-8601 text.

CREATE TABLE IF NOT EXISTS platform (
    id integer PRIMARY KEY,
    name text NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS asset (
    id integer PRIMARY KEY,
    symbol text NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS instrument (
    id integer PRIMARY KEY,
    platform_id integer NOT NULL REFERENCES platform (id),
    asset_id integer NOT NULL REFERENCES asset (id),
    source_id text NOT NULL,
    source_symbol text NOT NULL,
    discovered_at text NOT NULL,
    UNIQUE (platform_id, source_id),
    UNIQUE (platform_id, asset_id)
);

CREATE TABLE IF NOT EXISTS instrument_status (
    instrument_id integer NOT NULL REFERENCES instrument (id),
    since text NOT NULL,
    status text NOT NULL,
    PRIMARY KEY (instrument_id, since)
);

CREATE TABLE IF NOT EXISTS instrument_parameters (
    instrument_id integer NOT NULL REFERENCES instrument (id),
    effective_from text NOT NULL,
    max_leverage real NOT NULL,
    maintenance_margin real NOT NULL,
    min_notional real NOT NULL,
    liquidation_fee real,
    PRIMARY KEY (instrument_id, effective_from)
);

CREATE TABLE IF NOT EXISTS pair (
    id integer PRIMARY KEY,
    asset_id integer NOT NULL UNIQUE REFERENCES asset (id),
    polymarket_instrument_id integer NOT NULL UNIQUE REFERENCES instrument (id),
    hyperliquid_instrument_id integer NOT NULL UNIQUE REFERENCES instrument (id),
    paired_at text NOT NULL
);

CREATE TABLE IF NOT EXISTS fee_schedule (
    platform_id integer NOT NULL REFERENCES platform (id),
    effective_from text NOT NULL,
    category text NOT NULL,
    tier text NOT NULL,
    taker real NOT NULL,
    maker real NOT NULL,
    PRIMARY KEY (platform_id, effective_from, category, tier)
);

CREATE TABLE IF NOT EXISTS funding_reading (
    instrument_id integer NOT NULL REFERENCES instrument (id),
    source_time text NOT NULL,
    rate real NOT NULL,
    received_at text NOT NULL,
    origin text NOT NULL,
    PRIMARY KEY (instrument_id, source_time)
);

CREATE TABLE IF NOT EXISTS book_snapshot (
    instrument_id integer NOT NULL REFERENCES instrument (id),
    minute text NOT NULL,
    source_time text NOT NULL,
    best_bid real NOT NULL,
    best_ask real NOT NULL,
    bid_notional_05 real NOT NULL,
    ask_notional_05 real NOT NULL,
    bid_levels text NOT NULL,
    ask_levels text NOT NULL,
    bid_reach real NOT NULL,
    ask_reach real NOT NULL,
    PRIMARY KEY (instrument_id, minute)
);

CREATE TABLE IF NOT EXISTS price_reading (
    instrument_id integer NOT NULL REFERENCES instrument (id),
    minute text NOT NULL,
    mark_price real NOT NULL,
    index_price real NOT NULL,
    source_time text,
    received_at text NOT NULL,
    PRIMARY KEY (instrument_id, minute)
);

CREATE TABLE IF NOT EXISTS gap (
    id integer PRIMARY KEY,
    platform_id integer NOT NULL REFERENCES platform (id),
    instrument_id integer REFERENCES instrument (id),
    kind text NOT NULL,
    starts_at text NOT NULL,
    ends_at text NOT NULL,
    cause text,
    status text NOT NULL,
    closed_at text
);

CREATE INDEX IF NOT EXISTS gap_instrument_kind_start ON gap (instrument_id, kind, starts_at);

CREATE TRIGGER IF NOT EXISTS funding_reading_no_update BEFORE UPDATE ON funding_reading
BEGIN SELECT RAISE(ABORT, 'funding_reading is insert-only'); END;
CREATE TRIGGER IF NOT EXISTS funding_reading_no_delete BEFORE DELETE ON funding_reading
BEGIN SELECT RAISE(ABORT, 'funding_reading is insert-only'); END;

CREATE TRIGGER IF NOT EXISTS book_snapshot_no_update BEFORE UPDATE ON book_snapshot
BEGIN SELECT RAISE(ABORT, 'book_snapshot is insert-only'); END;
CREATE TRIGGER IF NOT EXISTS book_snapshot_no_delete BEFORE DELETE ON book_snapshot
BEGIN SELECT RAISE(ABORT, 'book_snapshot is insert-only'); END;

CREATE TRIGGER IF NOT EXISTS price_reading_no_update BEFORE UPDATE ON price_reading
BEGIN SELECT RAISE(ABORT, 'price_reading is insert-only'); END;
CREATE TRIGGER IF NOT EXISTS price_reading_no_delete BEFORE DELETE ON price_reading
BEGIN SELECT RAISE(ABORT, 'price_reading is insert-only'); END;

-- Evaluation tables of docs/design/data/schema.dbml. Evaluation only reads the tables above.

CREATE TABLE IF NOT EXISTS method (
    id integer PRIMARY KEY,
    name text NOT NULL UNIQUE,
    visibility text NOT NULL DEFAULT 'private'
);

CREATE TABLE IF NOT EXISTS variant (
    id integer PRIMARY KEY,
    method_id integer NOT NULL REFERENCES method (id),
    number integer NOT NULL,
    preregistration text NOT NULL,
    registered_at text NOT NULL,
    first_run_at text,
    UNIQUE (method_id, number)
);

CREATE TABLE IF NOT EXISTS run (
    id integer PRIMARY KEY,
    variant_id integer NOT NULL REFERENCES variant (id),
    mode text NOT NULL,
    starts_at text NOT NULL,
    ends_at text,
    status text NOT NULL,
    reason text,
    measured_from text
);

CREATE TABLE IF NOT EXISTS decision (
    run_id integer NOT NULL REFERENCES run (id),
    pair_id integer NOT NULL REFERENCES pair (id),
    hour text NOT NULL,
    action text NOT NULL CHECK (action IN ('open', 'hold', 'reverse', 'close', 'no_action')),
    data_until text NOT NULL,
    funding_spread real,
    cause text,
    PRIMARY KEY (run_id, pair_id, hour)
);

CREATE TABLE IF NOT EXISTS paper_position (
    id integer PRIMARY KEY,
    run_id integer NOT NULL REFERENCES run (id),
    pair_id integer NOT NULL REFERENCES pair (id),
    polymarket_side text NOT NULL,
    notional_per_leg real NOT NULL,
    leverage real NOT NULL,
    opened_at text NOT NULL,
    closed_at text,
    status text NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_trade (
    id integer PRIMARY KEY,
    position_id integer NOT NULL REFERENCES paper_position (id),
    platform_id integer NOT NULL REFERENCES platform (id),
    kind text NOT NULL,
    hour text NOT NULL,
    side text NOT NULL,
    avg_price real NOT NULL,
    best_price real NOT NULL,
    quantity real NOT NULL,
    fee real NOT NULL,
    slippage real NOT NULL,
    snapshot_minute text NOT NULL,
    loss real
);

CREATE TABLE IF NOT EXISTS paper_funding_payment (
    position_id integer NOT NULL REFERENCES paper_position (id),
    platform_id integer NOT NULL REFERENCES platform (id),
    source_time text NOT NULL,
    rate real NOT NULL,
    amount real NOT NULL,
    PRIMARY KEY (position_id, platform_id, source_time)
);

CREATE TABLE IF NOT EXISTS position_measurement (
    position_id integer NOT NULL REFERENCES paper_position (id),
    minute text NOT NULL,
    basis real,
    basis_change real,
    polymarket_liquidation_distance real,
    hyperliquid_liquidation_distance real,
    PRIMARY KEY (position_id, minute)
);

CREATE TABLE IF NOT EXISTS excluded_pair (
    run_id integer NOT NULL REFERENCES run (id),
    pair_id integer NOT NULL REFERENCES pair (id),
    expected_hours integer NOT NULL,
    hours_without_funding integer NOT NULL,
    expected_minutes integer NOT NULL,
    minutes_without_snapshot integer NOT NULL,
    reason text NOT NULL,
    PRIMARY KEY (run_id, pair_id)
);

CREATE TABLE IF NOT EXISTS verdict (
    run_id integer PRIMARY KEY REFERENCES run (id),
    issued_at text NOT NULL,
    outcome text NOT NULL,
    max_collateral real NOT NULL,
    annual_return_on_collateral real,
    breakdown text NOT NULL,
    variants_tested integer NOT NULL,
    reason text
);

CREATE TRIGGER IF NOT EXISTS variant_preregistration_frozen
BEFORE UPDATE OF preregistration ON variant WHEN OLD.first_run_at IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'variant preregistration is frozen once first_run_at is set'); END;
CREATE TRIGGER IF NOT EXISTS variant_delete_frozen BEFORE DELETE ON variant
WHEN OLD.first_run_at IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'variant is frozen once first_run_at is set'); END;
