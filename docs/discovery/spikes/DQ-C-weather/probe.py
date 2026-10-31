"""Probe C: does a bias-corrected public forecast beat the max-temperature market?

Disposable. On already-resolved markets, compares the market's probability against that of a
simple model (previous-day ECMWF forecast + bias and spread learned only from earlier days).
Uses mid prices every 3 h, not executable prices: it measures whether there is extra
information, not net edge (CR-001).
"""

import json
import math
import re
import statistics
import sys
import time
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / "cache"
CACHE.mkdir(exist_ok=True)

# Resolution station of each city, read from the description of its markets.
CITIES = {
    "nyc": {"lat": 40.7769, "lon": -73.8740, "tz": "America/New_York", "unit": "fahrenheit"},
    "london": {"lat": 51.5048, "lon": 0.0495, "tz": "Europe/London", "unit": "celsius"},
}
MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]


def get_json(url, name):
    file = CACHE / name
    if file.exists():
        return json.loads(file.read_text())
    # The Data API answers 403 to clients without a User-Agent.
    request = urllib.request.Request(url, headers={"User-Agent": "polyquack-probe/0.1"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as r:
                data = json.load(r)
            file.write_text(json.dumps(data))
            time.sleep(0.2)
            return data
        except Exception as e:  # noqa: BLE001 - probe, reported and retried
            print("  error", url[:80], e, file=sys.stderr)
            time.sleep(2)
    return None


def event(city, day):
    slug = f"highest-temperature-in-{city}-on-{MONTHS[day.month - 1]}-{day.day}-{day.year}"
    data = get_json(f"https://gamma-api.polymarket.com/events?slug={slug}", f"ev_{slug}.json")
    return data[0] if data else None


def bucket_range(title):
    """'56-57°F' -> (56, 57); '55°F or below' -> (-inf, 55); '74°F or higher' -> (74, inf)."""
    # The hyphen in "78-79" separates the range; it is a sign only if no digit precedes it ("-2°C").
    nums = [int(n) for n in re.findall(r"(?<!\d)-?\d+", title)]
    if "below" in title:
        return (-math.inf, nums[0])
    if "higher" in title or "above" in title:
        return (nums[0], math.inf)
    if len(nums) == 2:
        return (nums[0], nums[1])
    return (nums[0], nums[0])


def price_at(token, instant):
    data = get_json(
        f"https://data-api.polymarket.com/v2/prices-history?token_id={token}&interval=max&bucket_seconds=10800",
        f"ph_{token[:24]}.json",
    )
    if not data or not data.get("data"):
        return None
    earlier = [p for p in data["data"] if p["timestamp"] <= instant]
    return earlier[-1]["price"] if earlier else None


def forecast(city, day):
    c = CITIES[city]
    url = (
        "https://previous-runs-api.open-meteo.com/v1/forecast?"
        f"latitude={c['lat']}&longitude={c['lon']}&start_date={day}&end_date={day}"
        f"&hourly=temperature_2m_previous_day1&temperature_unit={c['unit']}"
        f"&timezone={c['tz']}&models=ecmwf_ifs025"
    )
    data = get_json(url, f"fc_{city}_{day}.json")
    values = [
        v
        for v in (data or {}).get("hourly", {}).get("temperature_2m_previous_day1", [])
        if v is not None
    ]
    return max(values) if len(values) >= 20 else None


def range_prob(lo, hi, mu, sigma):
    # The station reports whole degrees: the range [lo, hi] covers [lo - 0.5, hi + 0.5).
    cdf = lambda x: 0.5 * (1 + math.erf((x - mu) / (sigma * math.sqrt(2))))  # noqa: E731
    return cdf(hi + 0.5) - cdf(lo - 0.5)


def main():
    city = sys.argv[1]
    days = int(sys.argv[2])
    today = date(2026, 10, 24)
    rows = []
    for k in range(days, 0, -1):
        day = today - timedelta(days=k)
        ev = event(city, day)
        if not ev or not ev.get("closed"):
            continue
        fc = forecast(city, day)
        if fc is None:
            continue
        # Market snapshot at 16:00 UTC the day before (noon in New York).
        instant = int(datetime(day.year, day.month, day.day, 16, tzinfo=UTC).timestamp()) - 86400
        options = []
        for m in ev["markets"]:
            won = json.loads(m["outcomePrices"])[0] == "1"
            token = json.loads(m["clobTokenIds"])[0]
            options.append(
                {
                    "range": bucket_range(m["groupItemTitle"]),
                    "won": won,
                    "price": price_at(token, instant),
                    "rate": (m.get("feeSchedule") or {}).get("rate"),
                }
            )
        if sum(o["won"] for o in options) != 1 or any(o["price"] is None for o in options):
            continue
        winner = next(o for o in options if o["won"])
        rows.append({"day": str(day), "fc": fc, "options": options, "winner": winner["range"]})
        print(day, "forecast", round(fc, 1), "won", winner["range"], flush=True)

    (HERE / f"rows_{city}.json").write_text(json.dumps(rows, default=str))
    evaluate(city, rows)


def evaluate(city, rows):
    """Walk-forward: each day's bias and spread are learned only from earlier days."""
    errors = []
    res = []
    warmup = 14
    for f in rows:
        lo, hi = f["winner"]
        center = hi if lo == -math.inf else lo if hi == math.inf else (lo + hi) / 2
        if len(errors) >= warmup:
            bias = statistics.mean(errors)
            sigma = max(statistics.stdev(errors), 0.8)
            mu = f["fc"] + bias
            market_sum = sum(o["price"] for o in f["options"])
            b_mod = b_mkt = b_mix = 0.0
            ll_mod = ll_mkt = 0.0
            for o in f["options"]:
                p_mod = range_prob(*o["range"], mu, sigma)
                p_mkt = o["price"] / market_sum
                # If the blend beats the market alone, the forecast carries information the price lacks.
                p_mix = 0.8 * p_mkt + 0.2 * p_mod
                y = 1.0 if o["won"] else 0.0
                b_mod += (p_mod - y) ** 2
                b_mkt += (p_mkt - y) ** 2
                b_mix += (p_mix - y) ** 2
                if o["won"]:
                    ll_mod = -math.log(max(p_mod, 1e-6))
                    ll_mkt = -math.log(max(p_mkt, 1e-6))
            res.append(
                {
                    "day": f["day"],
                    "brier_model": b_mod,
                    "brier_market": b_mkt,
                    "brier_blend": b_mix,
                    "log_model": ll_mod,
                    "log_market": ll_mkt,
                    "market_sum": market_sum,
                }
            )
        # The center of the winning range approximates the true max (the station gives whole degrees).
        errors.append(center - f["fc"])

    if not res:
        print("no evaluable days")
        return
    n = len(res)
    summary = {
        "city": city,
        "days_evaluated": n,
        "brier_model": statistics.mean(r["brier_model"] for r in res),
        "brier_market": statistics.mean(r["brier_market"] for r in res),
        "brier_blend_80_20": statistics.mean(r["brier_blend"] for r in res),
        "log_model": statistics.mean(r["log_model"] for r in res),
        "log_market": statistics.mean(r["log_market"] for r in res),
        "days_model_better_brier": sum(r["brier_model"] < r["brier_market"] for r in res),
        "market_sum_mean": statistics.mean(r["market_sum"] for r in res),
    }
    (HERE / f"summary_{city}.json").write_text(
        json.dumps({"summary": summary, "days": res}, indent=1)
    )
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
