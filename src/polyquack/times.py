from datetime import UTC, datetime, timedelta

MINUTE_MS = 60_000
HOUR_MS = 3_600_000
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def iso(ms: int) -> str:
    """UTC ISO-8601 with millisecond precision; fixed width so text order equals time order."""
    moment = _EPOCH + timedelta(milliseconds=ms)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def from_iso(text: str) -> int:
    return (datetime.fromisoformat(text) - _EPOCH) // timedelta(milliseconds=1)


def floor_to(ms: int, step_ms: int) -> int:
    return ms - ms % step_ms
