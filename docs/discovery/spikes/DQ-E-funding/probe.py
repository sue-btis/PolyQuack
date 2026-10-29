"""Probe E1: does the Polymarket Perps funding rate diverge from Hyperliquid's enough
to collect the difference with a neutral position? (disposable)

Both platforms charge funding every hour. Simulated strategy, walk-forward by day:
if the average spread of the previous 24 h exceeds a threshold, the position that collects
is held for the next 24 h (short where the rate is higher, long where it is lower).
Taker fee on open and on close on both legs. It does not model basis risk
(the two prices drifting apart) or liquidations.
"""

import json
import statistics
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / "cache"
CACHE.mkdir(exist_ok=True)
UA = {"User-Agent": "polyquack-probe/0.1"}
START_MS = int(datetime(2026, 9, 3, tzinfo=UTC).timestamp() * 1000)
END_MS = int(datetime(2026, 10, 26, tzinfo=UTC).timestamp() * 1000)
# Base tier of each platform (new account), read from its documentation on Oct 26, 2026.
PM_FEE = 0.0004
HL_FEE = 0.00045
# Hourly thresholds: 0.00001 per hour is 8.8% per year.
THRESHOLDS = (0.0, 0.000005, 0.00001, 0.00002)


def http(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = dict(UA, **({"Content-Type": "application/json"} if body is not None else {}))
    req = urllib.request.Request(url, data=data, headers=headers)
    for wait in (2, 5, 15, 30):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(wait)
    raise RuntimeError(f"persistent 429 on {url}")


def cached(name, fn):
    file = CACHE / name
    if file.exists():
        return json.loads(file.read_text())
    data = fn()
    file.write_text(json.dumps(data))
    return data


def pm_funding(instrument_id):
    # The API returns newest to oldest, 100 per page: paginate backwards.
    rows, until = [], END_MS
    while True:
        r = http(
            f"https://api.perpetuals.polymarket.com/v1/info/funding?instrument_id={instrument_id}"
            f"&start_timestamp={START_MS}&end_timestamp={until}"
        )
        rows += r["data"]
        if not r.get("more") or not r["data"]:
            return rows
        until = min(f["timestamp"] for f in r["data"]) - 1
        time.sleep(0.8)


def hl_funding(coin):
    rows, since = [], START_MS
    while since < END_MS:
        r = http(
            "https://api.hyperliquid.xyz/info",
            {"type": "fundingHistory", "coin": coin, "startTime": since, "endTime": END_MS},
        )
        if not r:
            break
        rows += r
        since = max(f["time"] for f in r) + 1
        time.sleep(0.8)
    return rows


def by_hour(rows, time_field, rate_field):
    return {int(f[time_field]) // 3_600_000: float(f[rate_field]) for f in rows}


def simulate(hours, spread, threshold):
    """spread[h] = PM rate − HL rate. Side +1: short PM / long HL collects spread; side −1 collects −spread."""
    collected = fees = 0.0
    side = 0
    hours_in_position = 0
    for i in range(24, len(hours), 24):
        previous = statistics.mean(spread[h] for h in hours[i - 24 : i])
        new = 0 if abs(previous) <= threshold else (1 if previous > 0 else -1)
        if new != side:
            # Close and open: each change costs both legs once per trade.
            trades = (1 if side else 0) + (1 if new else 0)
            fees += trades * (PM_FEE + HL_FEE)
            side = new
        for h in hours[i : i + 24]:
            if side:
                collected += side * spread[h]
                hours_in_position += 1
    if side:
        fees += PM_FEE + HL_FEE
    return collected, fees, hours_in_position


def main():
    instruments = cached(
        "instruments.json",
        lambda: http("https://api.perpetuals.polymarket.com/v1/info/instruments"),
    )
    hl_meta = cached(
        "meta_hl.json", lambda: http("https://api.hyperliquid.xyz/info", {"type": "meta"})
    )
    hl_coins = {a["name"] for a in hl_meta["universe"]}
    crypto = [
        i for i in instruments if i.get("category") == "crypto" and i["base_asset"] in hl_coins
    ]
    results = []
    for inst in crypto:
        coin = inst["base_asset"]
        pm = by_hour(
            cached(f"pm_{coin}.json", lambda: pm_funding(inst["instrument_id"])),
            "timestamp",
            "funding_rate",
        )
        hl = by_hour(cached(f"hl_{coin}.json", lambda: hl_funding(coin)), "time", "fundingRate")
        hours = sorted(set(pm) & set(hl))
        if len(hours) < 24 * 7:
            continue
        spread = {h: pm[h] - hl[h] for h in hours}
        values = list(spread.values())
        row = {
            "coin": coin,
            "hours": len(hours),
            "pm_mean_annual": statistics.mean(pm[h] for h in hours) * 24 * 365,
            "hl_mean_annual": statistics.mean(hl[h] for h in hours) * 24 * 365,
            "mean_annual_diff": statistics.mean(values) * 24 * 365,
            "mean_annual_abs_diff": statistics.mean(abs(v) for v in values) * 24 * 365,
            "pm_higher_share": sum(v > 0 for v in values) / len(values),
        }
        days = len(hours) / 24
        for u in THRESHOLDS:
            collected, fees, in_pos = simulate(hours, spread, u)
            net = collected - fees
            row[f"annual_net_u{u}"] = net * 365 / days
            row[f"in_position_u{u}"] = in_pos / len(hours)
        results.append(row)
        print(
            coin,
            len(hours),
            "h",
            "avg annual spread",
            f"{row['mean_annual_diff']:+.1%}",
            "net (u=0.00001)",
            f"{row['annual_net_u1e-05']:+.1%}",
            flush=True,
        )

    results.sort(key=lambda f: -f["annual_net_u1e-05"])
    (HERE / "result.json").write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
