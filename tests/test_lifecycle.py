import asyncio
import json
import logging
from pathlib import Path

import pytest

from polyquack.ingestion.models import FeeRate
from polyquack.ingestion.platforms import HYPERLIQUID, POLYMARKET
from polyquack.ingestion.service import INSTRUMENTS_REFRESH_SECONDS, MissingPairError, Service
from polyquack.status import render_status
from polyquack.storage.db import Database
from polyquack.times import HOUR_MS, from_iso, iso

from .conftest import T0, no_sleep, seed_pairs
from .exchange import FakeExchange, hl_row, pm_row


def _service(
    db: Database, exchange: FakeExchange, clock: list[int], assets: tuple[str, ...] = ()
) -> Service:
    return Service(db, exchange.platforms(), assets, clock=lambda: clock[0], sleep=no_sleep)


def _refresh(service: Service) -> None:
    for name in (POLYMARKET, HYPERLIQUID):
        assert asyncio.run(service.refresh_instruments(name))


def _statuses(db: Database, source_id: str, platform: str) -> list[tuple[str, str]]:
    rows = db.conn.execute(
        "SELECT s.since, s.status FROM instrument_status s"
        " JOIN instrument i ON i.id = s.instrument_id"
        " JOIN platform p ON p.id = i.platform_id WHERE p.name = ? AND i.source_id = ?"
        " ORDER BY s.since",
        (platform, source_id),
    ).fetchall()
    return [(str(a), str(b)) for a, b in rows]


def _btc_world() -> FakeExchange:
    exchange = FakeExchange()
    exchange.pm_rows = {6: pm_row(6, "BTC")}
    exchange.hl_rows = [hl_row("BTC")]
    return exchange


def test_status_follows_polymarket_from_active_to_close_only_to_settled(db: Database) -> None:
    exchange, clock = _btc_world(), [T0]
    service = _service(db, exchange, clock)

    _refresh(service)
    clock[0] = T0 + HOUR_MS
    exchange.pm_rows[6] = pm_row(6, "BTC", close_only=True)
    _refresh(service)
    clock[0] = T0 + 2 * HOUR_MS
    del exchange.pm_rows[6]
    exchange.settled.add(6)
    _refresh(service)

    rows = _statuses(db, "6", POLYMARKET)
    assert [status for _, status in rows] == ["active", "close_only", "delisted"]
    assert [since for since, _ in rows] == [iso(T0), iso(T0 + HOUR_MS), iso(T0 + 2 * HOUR_MS)]
    assert db.pair_statuses() == {"BTC": "delisted"}
    assert db.targets() == []


def test_unchanged_status_adds_no_row(db: Database) -> None:
    exchange, clock = _btc_world(), [T0]
    service = _service(db, exchange, clock)

    _refresh(service)
    clock[0] += HOUR_MS
    _refresh(service)

    assert len(_statuses(db, "6", POLYMARKET)) == 1
    assert len(_statuses(db, "BTC", HYPERLIQUID)) == 1


def test_instrument_absent_without_settlement_keeps_its_status_and_is_logged(
    db: Database, caplog: pytest.LogCaptureFixture
) -> None:
    exchange, clock = _btc_world(), [T0]
    service = _service(db, exchange, clock)
    _refresh(service)
    del exchange.pm_rows[6]

    with caplog.at_level(logging.WARNING):
        _refresh(service)

    assert [s for _, s in _statuses(db, "6", POLYMARKET)] == ["active"]
    assert "6 is absent" in caplog.text


def test_absent_instrument_whose_lookup_has_no_settlement_keeps_its_status(
    db: Database, caplog: pytest.LogCaptureFixture
) -> None:
    exchange, clock = _btc_world(), [T0]
    service = _service(db, exchange, clock)
    _refresh(service)
    del exchange.pm_rows[6]
    exchange.lookup_returns_row_without_settlement = True
    clock[0] += HOUR_MS

    with caplog.at_level(logging.WARNING):
        _refresh(service)

    assert [s for _, s in _statuses(db, "6", POLYMARKET)] == ["active"]
    assert "6 is absent" in caplog.text


def test_hyperliquid_delisted_coin_is_stored_as_delisted_and_never_paired(db: Database) -> None:
    exchange, clock = _btc_world(), [T0]
    exchange.hl_rows = [hl_row("BTC", delisted=True)]
    service = _service(db, exchange, clock)

    _refresh(service)

    assert [s for _, s in _statuses(db, "BTC", HYPERLIQUID)] == ["delisted"]
    assert db.conn.execute("SELECT count(*) FROM pair").fetchone()[0] == 0
    assert db.unpaired_instruments() == [(POLYMARKET, "BTC-USD")]


def test_pair_status_is_derived_from_the_worst_instrument(db: Database) -> None:
    exchange, clock = FakeExchange(), [T0]
    exchange.pm_rows = {1: pm_row(1, "AAA"), 2: pm_row(2, "BBB", close_only=True)}
    exchange.hl_rows = [hl_row("AAA"), hl_row("BBB")]
    service = _service(db, exchange, clock)
    _refresh(service)
    assert db.pair_statuses() == {"AAA": "active", "BBB": "close_only"}

    clock[0] += HOUR_MS
    exchange.hl_rows = [hl_row("AAA"), hl_row("BBB", delisted=True)]
    _refresh(service)

    assert db.pair_statuses() == {"AAA": "active", "BBB": "delisted"}
    assert {t.asset for t in db.targets()} == {"AAA"}


def test_targets_are_every_non_delisted_pair_narrowed_by_the_filter(db: Database) -> None:
    seed_pairs(db, ["AAA", "BBB", "CCC"])
    db.set_status(db.targets(("CCC",))[0].instrument_id, "delisted", T0)

    assert {t.asset for t in db.targets()} == {"AAA", "BBB"}
    assert {t.asset for t in db.targets(("BBB",))} == {"BBB"}
    assert db.targets(("CCC",)) == []


def test_each_filter_asset_without_a_target_pair_is_warned_about(
    db: Database, caplog: pytest.LogCaptureFixture
) -> None:
    seed_pairs(db, ["AAA", "BBB"])
    db.set_status(db.targets(("BBB",))[0].instrument_id, "delisted", T0)
    exchange = FakeExchange()
    service = Service(db, exchange.platforms(), ("AAA", "BBB", "CCC"), clock=lambda: T0)

    with caplog.at_level(logging.WARNING):
        service._load_targets()

    assert {t.asset for t in service.targets} == {"AAA"}
    warned = [r.getMessage() for r in caplog.records if "no target pair" in r.getMessage()]
    assert sorted(warned) == [
        "filter asset BBB has no target pair",
        "filter asset CCC has no target pair",
    ]


def test_parameters_are_stored_once_and_again_only_when_a_value_changes(db: Database) -> None:
    exchange, clock = _btc_world(), [T0]
    service = _service(db, exchange, clock)
    sql = (
        "SELECT p.name, ip.effective_from, ip.max_leverage, ip.maintenance_margin,"
        " ip.min_notional, ip.liquidation_fee FROM instrument_parameters ip"
        " JOIN instrument i ON i.id = ip.instrument_id JOIN platform p ON p.id = i.platform_id"
        " ORDER BY p.id, ip.effective_from"
    )

    _refresh(service)
    clock[0] += HOUR_MS
    _refresh(service)

    assert db.conn.execute(sql).fetchall() == [
        (POLYMARKET, iso(T0), 50.0, 0.01, 10.0, 0.005),
        (HYPERLIQUID, iso(T0), 40.0, 0.0125, 10.0, None),
    ]

    exchange.pm_rows[6] = pm_row(6, "BTC", max_leverage=25)
    _refresh(service)

    polymarket = [row for row in db.conn.execute(sql).fetchall() if row[0] == POLYMARKET]
    assert [row[2] for row in polymarket] == [50.0, 25.0]


def _fee_rows(db: Database) -> list[tuple[object, ...]]:
    return db.conn.execute(
        "SELECT p.name, f.effective_from, f.category, f.tier, f.taker, f.maker FROM fee_schedule f"
        " JOIN platform p ON p.id = f.platform_id"
        " ORDER BY p.id, f.effective_from, f.category, f.tier"
    ).fetchall()


def test_fees_of_both_platforms_are_stored_dated_and_not_repeated(db: Database) -> None:
    exchange, clock = _btc_world(), [T0]
    fixture = Path(__file__).parent / "fixtures" / "pm_fees.json"
    exchange.pm_fees = json.loads(fixture.read_text(encoding="utf-8"))["fee_schedule"]
    service = _service(db, exchange, clock)

    _refresh(service)
    clock[0] += HOUR_MS
    _refresh(service)

    rows = _fee_rows(db)
    assert len(rows) == 9
    assert rows[0] == (POLYMARKET, "2026-10-21T00:00:00.000Z", "crypto", "0", 0.0004, 0.000125)
    assert rows[1] == (POLYMARKET, iso(T0), "equity", "0", 0.0004, 0.000125)
    assert rows[-1] == (HYPERLIQUID, "2026-10-30T00:00:00.000Z", "", "0", 0.00045, 0.00015)


def test_a_changed_polymarket_rate_is_a_new_dated_row_set(db: Database) -> None:
    exchange, clock = _btc_world(), [T0]
    tier = {"min_volume_30d": "0", "taker_fee_rate": "0.0004", "maker_fee_rate": "0.0001"}
    exchange.pm_fees = [{"category": "crypto", "tiers": [tier]}]
    service = _service(db, exchange, clock)
    _refresh(service)
    clock[0] += HOUR_MS
    tier["taker_fee_rate"] = "0.0005"

    _refresh(service)

    polymarket = [row for row in _fee_rows(db) if row[0] == POLYMARKET and str(row[1]) >= iso(T0)]
    assert [(row[1], row[4]) for row in polymarket] == [
        (iso(T0), 0.0004),
        (iso(T0 + HOUR_MS), 0.0005),
    ]


def test_hyperliquid_fee_entries_come_from_the_versioned_data_file() -> None:
    rates = asyncio.run(_btc_world().platforms()[HYPERLIQUID].fees())

    assert rates == [FeeRate("", "0", 0.00045, 0.00015, from_iso("2026-10-30T00:00:00.000Z"))]


async def _idle(self: Service) -> None:
    await asyncio.Event().wait()


def test_target_set_change_ends_run_with_a_log_and_no_exception(
    db: Database, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    exchange = _btc_world()
    switched: list[bool] = []

    async def switch_world(seconds: float) -> None:
        await asyncio.sleep(0)
        if seconds == INSTRUMENTS_REFRESH_SECONDS and not switched:
            switched.append(True)
            exchange.pm_rows[7] = pm_row(7, "ETH")
            exchange.hl_rows.append(hl_row("ETH"))

    monkeypatch.setattr(Service, "_ingest", _idle)
    service = Service(db, exchange.platforms(), (), clock=lambda: T0, sleep=switch_world)

    with caplog.at_level(logging.WARNING):
        asyncio.run(asyncio.wait_for(service.run(), timeout=10))

    assert "target pairs changed from ['BTC'] to ['BTC', 'ETH']" in caplog.text


def test_run_fails_when_no_pair_can_be_ingested(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    exchange = FakeExchange()
    exchange.pm_rows = {6: pm_row(6, "BTC")}
    exchange.hl_rows = [hl_row("ETH")]
    monkeypatch.setattr(Service, "_ingest", _idle)
    service = Service(db, exchange.platforms(), (), clock=lambda: T0, sleep=no_sleep)

    with pytest.raises(ExceptionGroup) as raised:
        asyncio.run(asyncio.wait_for(service.run(), timeout=10))

    assert raised.group_contains(MissingPairError)


def test_status_lists_every_target_pair_with_its_derived_status(db: Database) -> None:
    exchange, clock = FakeExchange(), [T0]
    exchange.pm_rows = {1: pm_row(1, "AAA"), 2: pm_row(2, "BBB", close_only=True)}
    exchange.hl_rows = [hl_row("AAA"), hl_row("BBB")]
    _refresh(_service(db, exchange, clock))

    text = render_status(db, (), T0 + HOUR_MS)
    filtered = render_status(db, ("BBB",), T0 + HOUR_MS)

    assert "Pair AAA [active]" in text and "Pair BBB [close_only]" in text
    assert text.count(f"{POLYMARKET} (instrument") == 2
    assert "Pair AAA" not in filtered and "Pair BBB [close_only]" in filtered
