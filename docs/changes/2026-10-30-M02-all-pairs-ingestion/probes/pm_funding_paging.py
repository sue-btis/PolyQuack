"""Read-only probe: page Polymarket Perps BTC funding back to 2026-09-03 by moving end_timestamp below the oldest row."""

import json
import time

import httpx

PM = "https://api.perpetuals.polymarket.com"
FLOOR_MS = 1788393600000  # 2026-09-03T00:00:00Z


def main() -> None:
    end = int(time.time() * 1000)
    pages, seen, order = 0, set(), None
    with httpx.Client(timeout=20) as http:
        while True:
            body = http.get(
                f"{PM}/v1/info/funding",
                params={"instrument_id": "6", "start_timestamp": FLOOR_MS, "end_timestamp": end},
            ).json()
            pages += 1
            stamps = [int(r["timestamp"]) for r in body["data"]]
            if order is None and len(stamps) > 1:
                order = "descending" if stamps[0] > stamps[-1] else "ascending"
            seen.update(stamps)
            if not body.get("more") or not stamps:
                break
            end = min(stamps) - 1
            time.sleep(1)
    hours = sorted(seen)
    gaps = [
        (a, b) for a, b in zip(hours, hours[1:]) if b - a > 3_600_000 + 60_000
    ]
    print(json.dumps({
        "pages": pages,
        "rows": len(hours),
        "order_in_page": order,
        "oldest": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(hours[0] / 1000)),
        "newest": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(hours[-1] / 1000)),
        "missing_hour_runs": len(gaps),
    }, indent=1))


if __name__ == "__main__":
    main()
