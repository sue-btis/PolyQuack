import json
from dataclasses import dataclass
from typing import Any

from polyquack.storage.db import Database
from polyquack.times import iso

HORIZON_DAYS = 28
CRITERION_ANNUAL_NET_RETURN = 0.10
SIZE_PER_LEG_USD = 1000
LEVERAGE = 2
DECISION_MINUTE = 21
SNAPSHOT_MAX_AGE_SECONDS = 120


class InvalidPreregistration(ValueError):
    pass


@dataclass(frozen=True)
class Preregistration:
    method: str
    window_hours: int
    entry: float
    exit: float
    size_per_leg: float
    leverage: float
    decision_minute: int
    snapshot_max_age_s: int
    horizon_days: int
    min_annual_return: float


@dataclass(frozen=True)
class Registered:
    method: str
    number: int
    replaced: bool


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidPreregistration(f"{name} must be an object")
    return value


def _text(document: dict[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidPreregistration(f"{key} must be a non-empty string")
    return value


def _number(document: dict[str, Any], key: str) -> float:
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidPreregistration(f"{key} must be a number")
    return float(value)


def _fixed(document: dict[str, Any], key: str, expected: float) -> float:
    value = _number(document, key)
    if value != expected:
        raise InvalidPreregistration(f"{key} must be {expected}")
    return value


def parse_preregistration(text: str) -> Preregistration:
    try:
        document = _mapping(json.loads(text), "preregistration")
    except json.JSONDecodeError as error:
        raise InvalidPreregistration(f"not valid JSON: {error}") from error
    rules = _mapping(document.get("rules"), "rules")
    window = rules.get("window_hours")
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise InvalidPreregistration("window_hours must be an integer of at least 1")
    entry = _number(rules, "entry")
    exit_threshold = _number(rules, "exit")
    if not 0 <= exit_threshold < entry:
        raise InvalidPreregistration("rules must satisfy 0 <= exit < entry")
    _text(document, "metric")
    horizon_days = int(_fixed(document, "horizon_days", HORIZON_DAYS))
    criterion = _mapping(document.get("criterion"), "criterion")
    min_annual_return = _fixed(
        criterion, "min_annual_net_return_on_collateral", CRITERION_ANNUAL_NET_RETURN
    )
    return Preregistration(
        method=_text(document, "method"),
        window_hours=window,
        entry=entry,
        exit=exit_threshold,
        size_per_leg=_fixed(document, "size_per_leg_usd", SIZE_PER_LEG_USD),
        leverage=_fixed(document, "leverage", LEVERAGE),
        decision_minute=int(_fixed(document, "decision_minute", DECISION_MINUTE)),
        snapshot_max_age_s=int(
            _fixed(document, "snapshot_max_age_seconds", SNAPSHOT_MAX_AGE_SECONDS)
        ),
        horizon_days=horizon_days,
        min_annual_return=min_annual_return,
    )


def preregister(db: Database, text: str, now_ms: int) -> Registered:
    """Store the preregistration as the method's next variant, or replace one that has not run."""
    method = parse_preregistration(text).method
    registered_at = iso(now_ms)
    with db.conn:
        db.conn.execute("INSERT OR IGNORE INTO method (name) VALUES (?)", (method,))
        method_id = db.conn.execute("SELECT id FROM method WHERE name = ?", (method,)).fetchone()[0]
        latest = db.conn.execute(
            "SELECT id, number, first_run_at FROM variant WHERE method_id = ?"
            " ORDER BY number DESC LIMIT 1",
            (method_id,),
        ).fetchone()
        if latest is not None and latest[2] is None:
            db.conn.execute(
                "UPDATE variant SET preregistration = ?, registered_at = ? WHERE id = ?",
                (text, registered_at, latest[0]),
            )
            return Registered(method, latest[1], True)
        number = 1 if latest is None else latest[1] + 1
        db.conn.execute(
            "INSERT INTO variant (method_id, number, preregistration, registered_at)"
            " VALUES (?, ?, ?, ?)",
            (method_id, number, text, registered_at),
        )
    return Registered(method, number, False)


def render_variants(db: Database) -> str:
    rows = db.conn.execute(
        "SELECT m.name, v.number, v.registered_at, v.first_run_at FROM variant v"
        " JOIN method m ON m.id = v.method_id ORDER BY m.name, v.number"
    ).fetchall()
    if not rows:
        return "No methods preregistered."
    lines: list[str] = []
    for method in dict.fromkeys(row[0] for row in rows):
        variants = [row for row in rows if row[0] == method]
        ran = sum(1 for row in variants if row[3] is not None)
        lines.append(f"{method}: {len(variants)} registered, {ran} run")
        lines += [
            f"  variant {row[1]}: registered {row[2]}, "
            + ("not run yet" if row[3] is None else f"first run {row[3]}")
            for row in variants
        ]
    return "\n".join(lines)
