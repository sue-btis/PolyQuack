"""Downloads the active Gamma events to eventos.json, keeping only the fields the probe needs (disposable)."""

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Offset listing is cut off at 2,500; keyset has no such cap.
BASE = "https://gamma-api.polymarket.com/events/keyset?closed=false&active=true&limit=500"
EVENT_FIELDS = ("id", "slug", "title", "negRisk", "endDate")
MARKET_FIELDS = (
    "question",
    "groupItemTitle",
    "groupItemThreshold",
    "clobTokenIds",
    "bestBid",
    "bestAsk",
    "feeSchedule",
    "endDate",
    "closed",
    "acceptingOrders",
    "negRisk",
    "liquidityNum",
    "orderMinSize",
    "orderPriceMinTickSize",
)


def trim(event):
    short = {k: event.get(k) for k in EVENT_FIELDS}
    short["markets"] = [{k: m.get(k) for k in MARKET_FIELDS} for m in event.get("markets", [])]
    return short


events = []
cursor = None
while True:
    url = BASE + (f"&after_cursor={urllib.parse.quote(cursor)}" if cursor else "")
    with urllib.request.urlopen(url, timeout=60) as r:
        page = json.load(r)
    events.extend(trim(e) for e in page["events"])
    print(len(events), "events", flush=True)
    cursor = page.get("next_cursor")
    if not cursor or not page["events"]:
        break
    time.sleep(0.3)

output = Path(__file__).with_name("eventos.json")
output.write_text(
    json.dumps(
        {"descargado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "eventos": events}
    )
)
print(len(events), "events,", sum(len(e["markets"]) for e in events), "markets")
