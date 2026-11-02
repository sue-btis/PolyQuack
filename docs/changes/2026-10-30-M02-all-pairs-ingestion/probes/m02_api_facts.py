"""Read-only probe of the public endpoints for the M02 audit: pair count, funding history depth and paging, instrument fields."""

import json
import time

import httpx

PM = "https://api.perpetuals.polymarket.com"
HL = "https://api.hyperliquid.xyz/info"
FLOOR_MS = 1788393600000  # 2026-09-03T00:00:00Z


def iso(ms: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000))


def main() -> None:
    out: dict[str, object] = {}
    with httpx.Client(timeout=20) as http:
        pm = http.get(f"{PM}/v1/info/instruments").json()
        time.sleep(1)
        hl = http.post(HL, json={"type": "meta"}).json()["universe"]
        time.sleep(1)
        out["pm_instrument_keys"] = sorted(pm[0].keys())
        out["pm_instrument_btc"] = next(r for r in pm if r["base_asset"] == "BTC")
        out["hl_universe_keys"] = sorted({k for r in hl for k in r})
        out["hl_universe_btc"] = next(r for r in hl if r["name"] == "BTC")
        pm_assets = {r["base_asset"] for r in pm}
        hl_live = {r["name"] for r in hl if not r.get("isDelisted")}
        out["pm_count"], out["hl_live_count"] = len(pm), len(hl_live)
        out["paired_exact"] = sorted(pm_assets & hl_live)
        out["pm_status_values"] = sorted({str(r.get("status")) for r in pm})

        btc_pm = str(out["pm_instrument_btc"]["instrument_id"])  # type: ignore[index]
        now = int(time.time() * 1000)
        pm_f = http.get(
            f"{PM}/v1/info/funding",
            params={"instrument_id": btc_pm, "start_timestamp": FLOOR_MS, "end_timestamp": now},
        ).json()
        time.sleep(1)
        rows = pm_f["data"]
        out["pm_funding_page"] = {
            "keys": sorted(k for k in pm_f if k != "data"),
            "meta": {k: v for k, v in pm_f.items() if k != "data"},
            "rows": len(rows),
            "first": iso(min(int(r["timestamp"]) for r in rows)) if rows else None,
            "last": iso(max(int(r["timestamp"]) for r in rows)) if rows else None,
        }
        hl_f = http.post(
            HL, json={"type": "fundingHistory", "coin": "BTC", "startTime": FLOOR_MS, "endTime": now}
        ).json()
        out["hl_funding_page"] = {
            "rows": len(hl_f),
            "first": iso(min(int(r["time"]) for r in hl_f)) if hl_f else None,
            "last": iso(max(int(r["time"]) for r in hl_f)) if hl_f else None,
        }
        out["hours_since_floor"] = (now - FLOOR_MS) // 3_600_000
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
