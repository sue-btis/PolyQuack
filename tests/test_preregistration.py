import json
import sqlite3
from pathlib import Path

import pytest

from polyquack.cli import main
from polyquack.evaluation.preregistration import (
    InvalidPreregistration,
    parse_preregistration,
    preregister,
    render_variants,
)
from polyquack.evaluation.runner import evaluate
from polyquack.storage.db import Database
from polyquack.times import iso

from .evalkit import D0, H0, prereg, prereg_text, seed_world

REGISTERED_AT = H0 - 1_800_000


def test_r1_valid_preregistration_yields_the_rule_and_the_fixed_parameters() -> None:
    parsed = parse_preregistration(prereg_text())

    assert (parsed.method, parsed.window_hours, parsed.entry, parsed.exit) == (
        "E1",
        3,
        0.0002,
        0.00005,
    )
    assert (parsed.size_per_leg, parsed.leverage) == (1000, 2)
    assert (parsed.decision_minute, parsed.snapshot_max_age_s) == (21, 120)


@pytest.mark.parametrize(
    "overrides",
    [
        {"method": ""},
        {"rules": {"window_hours": 0, "entry": 0.0002, "exit": 0.00005}},
        {"rules": {"window_hours": 2.5, "entry": 0.0002, "exit": 0.00005}},
        {"rules": {"window_hours": 3, "entry": 0.0002, "exit": 0.0002}},
        {"rules": {"window_hours": 3, "entry": 0.0002, "exit": -0.1}},
        {"rules": {"window_hours": 3, "entry": 0.0002}},
        {"rules": {"window_hours": True, "entry": 0.0002, "exit": 0.00005}},
        {"metric": ""},
        {"horizon_days": 14},
        {"criterion": {"min_annual_net_return_on_collateral": 0.2}},
        {"size_per_leg_usd": 500},
        {"leverage": 3},
        {"decision_minute": 20},
        {"snapshot_max_age_seconds": 60},
    ],
)
def test_r1_invalid_preregistration_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(InvalidPreregistration):
        parse_preregistration(prereg_text(**overrides))


def test_r1_a_missing_field_or_malformed_json_is_rejected() -> None:
    document = prereg()
    del document["leverage"]

    with pytest.raises(InvalidPreregistration):
        parse_preregistration(json.dumps(document))
    with pytest.raises(InvalidPreregistration):
        parse_preregistration("{not json")


def test_ac1_a_variant_without_a_run_is_replaced_and_one_with_a_run_gets_a_next_number(
    db: Database,
) -> None:
    seed_world(db)
    changed = prereg_text(rules={"window_hours": 4, "entry": 0.0003, "exit": 0.0001})
    first = preregister(db, prereg_text(), REGISTERED_AT)
    replaced = preregister(db, changed, REGISTERED_AT + 1)
    evaluate(db, D0 + 60_000)

    second = preregister(db, prereg_text(), D0 + 120_000)

    assert (first.number, first.replaced) == (1, False)
    assert (replaced.number, replaced.replaced) == (1, True)
    assert (second.number, second.replaced) == (2, False)
    rows = db.conn.execute("SELECT number, registered_at FROM variant ORDER BY number").fetchall()
    assert [r[0] for r in rows] == [1, 2]
    assert rows[1][1] == iso(D0 + 120_000)
    stored = db.conn.execute("SELECT preregistration FROM variant WHERE number = 1").fetchone()[0]
    assert json.loads(stored)["rules"]["window_hours"] == 4


def test_ac1_an_update_of_a_run_variants_preregistration_fails(db: Database) -> None:
    seed_world(db)
    preregister(db, prereg_text(), REGISTERED_AT)
    evaluate(db, D0 + 60_000)

    with pytest.raises(sqlite3.IntegrityError, match="frozen"):
        db.conn.execute("UPDATE variant SET preregistration = '{}' WHERE number = 1")


def test_ac2_the_trigger_rejects_update_and_delete_once_first_run_at_is_set(db: Database) -> None:
    preregister(db, prereg_text(), REGISTERED_AT)
    with db.conn:
        db.conn.execute("UPDATE variant SET preregistration = '{}'")
        db.conn.execute("UPDATE variant SET first_run_at = ?", (iso(D0),))

    with pytest.raises(sqlite3.IntegrityError, match="frozen"):
        db.conn.execute("UPDATE variant SET preregistration = '{}'")
    with pytest.raises(sqlite3.IntegrityError, match="frozen"):
        db.conn.execute("DELETE FROM variant")
    db.conn.execute("UPDATE variant SET registered_at = registered_at")


def test_ac2_a_variant_without_first_run_can_still_be_deleted(db: Database) -> None:
    preregister(db, prereg_text(), REGISTERED_AT)

    with db.conn:
        db.conn.execute("DELETE FROM variant")


def test_ac3_variants_lists_registered_and_run_variants_per_method(db: Database) -> None:
    seed_world(db)
    preregister(db, prereg_text(), REGISTERED_AT)
    before = render_variants(db)
    evaluate(db, D0 + 60_000)
    preregister(db, prereg_text(), D0 + 120_000)

    after = render_variants(db)

    assert "E1: 1 registered, 0 run" in before
    assert "E1: 2 registered, 1 run" in after


def test_ac3_without_methods_variants_says_so(db: Database) -> None:
    assert render_variants(db) == "No methods preregistered."


def test_cli_preregister_then_variants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("POLYQUACK_DB", str(tmp_path / "cli.db"))
    file = tmp_path / "e1.json"
    file.write_text(prereg_text(), encoding="utf-8")

    assert main(["preregister", str(file)]) == 0
    assert main(["variants"]) == 0

    output = capsys.readouterr().out
    assert "E1 variant 1" in output
    assert "E1: 1 registered, 0 run" in output


def test_cli_preregister_rejects_an_invalid_file_and_stores_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "cli.db"
    monkeypatch.setenv("POLYQUACK_DB", str(database))
    file = tmp_path / "bad.json"
    file.write_text(prereg_text(leverage=9), encoding="utf-8")

    assert main(["preregister", str(file)]) == 1

    assert "leverage" in capsys.readouterr().err
    assert Database(database).conn.execute("SELECT count(*) FROM variant").fetchone()[0] == 0


def test_cli_preregister_needs_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("POLYQUACK_DB", str(tmp_path / "cli.db"))

    with pytest.raises(SystemExit) as exit_info:
        main(["preregister"])

    assert exit_info.value.code == 2
    assert "FILE" in capsys.readouterr().err
