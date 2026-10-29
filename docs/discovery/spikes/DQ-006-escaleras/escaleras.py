"""Probe B: template-based ladders in active markets (disposable).

A ladder is an event whose markets only change a threshold ("above X") or a deadline
("by X"). If A implies B, buying Yes on B and No on A pays at least 1 in every outcome;
there is an opportunity when the executable cost of that pair, with taker fee, is < 1.
"""

import json
import random
import re
import sys
import urllib.request
from datetime import date
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).parent
MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
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
    )
}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})

UP = re.compile(
    r"\b(above|over|reach|hit|at least|more than|greater than|exceed|higher than|or more|≥|>)", re.I
)
DOWN = re.compile(r"\b(below|under|dip|less than|lower than|fall to|drop to|or less|≤|<)", re.I)
DEADLINE = re.compile(r"\b(by|before|until|no later than)\b", re.I)
EXACT = re.compile(r"\b(on|in|during)\s+(the\s+)?(" + "|".join(MONTHS) + r")\b", re.I)


def number(text):
    t = text.replace(",", "")
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*([kmb])?\b", t, re.I)
    if not m:
        return None
    scale = {"k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(2) or "").lower(), 1)
    return float(m.group(1)) * scale


def parse_date(text, event_year):
    m = re.search(r"(" + "|".join(MONTHS) + r")[a-z]*\.?\s+(\d{1,2})(?:,?\s*(\d{4}))?", text, re.I)
    if not m:
        return None
    year = int(m.group(3)) if m.group(3) else event_year
    try:
        return date(year, MONTHS[m.group(1).lower()[:3]], int(m.group(2)))
    except ValueError:
        return None


def open_markets(event):
    return [
        m
        for m in event["markets"]
        if not m["closed"]
        and m.get("acceptingOrders")
        and m.get("bestAsk") is not None
        and m.get("bestBid") is not None
        and m.get("groupItemTitle")
    ]


EXPLICIT_UP = re.compile(
    r"\(HIGH\)|or (higher|more|above)|\babove\b|\bover\b|greater than|more than|at least|≥|>", re.I
)
EXPLICIT_DOWN = re.compile(
    r"\(LOW\)|or (lower|less|below)|\bbelow\b|\bunder\b|less than|fewer than|≤|<", re.I
)


def direction(question):
    """'up', 'down' or None. A bare "hit X" or "reach X" is ambiguous: it depends on the current value."""
    up, down = bool(EXPLICIT_UP.search(question)), bool(EXPLICIT_DOWN.search(question))
    return "up" if up and not down else "down" if down and not up else None


def ladders_of(event):
    """Groups by each market's explicit direction; an event can have two opposite ladders."""
    if event.get("negRisk"):
        return []
    markets = open_markets(event)
    if len(markets) < 2:
        return []
    c = classify_date(event, markets)
    if c:
        return [c]
    result = []
    for side, kind, sign in (("up", "umbral_arriba", 1), ("down", "umbral_abajo", -1)):
        group = [m for m in markets if direction(m["question"]) == side]
        nums = [number(m["groupItemTitle"]) for m in group]
        if len(group) >= 2 and None not in nums and len(set(nums)) == len(nums):
            result.append((kind, [(sign * n, m) for n, m in zip(nums, group)]))
    return result


def classify_date(event, open_markets):
    dates = []
    for m in open_markets:
        # The event's endDate does not always cover all its markets; each market's own does.
        # Pick the year that puts the date closest to the market close (Dec 31 closes Jan 1 UTC).
        close = date.fromisoformat((m.get("endDate") or "2026-12-31")[:10])
        candidates = [parse_date(m["groupItemTitle"], close.year + d) for d in (-1, 0, 1)]
        candidates = [f for f in candidates if f]
        dates.append(min(candidates, key=lambda f: abs((f - close).days)) if candidates else None)
    if not all(dates) or len(set(dates)) != len(dates):
        return None
    questions = " ".join(m["question"] for m in open_markets)
    if DEADLINE.search(questions) and not EXACT.search(event["title"]):
        return "fecha", [(-f.toordinal(), m) for f, m in zip(dates, open_markets)]
    return None


def classify(event, open_markets):
    """Returns (kind, [(key, market)]) or None. The key orders from the easiest Yes to the hardest."""
    if len(open_markets) < 2:
        return None
    questions = " ".join(m["question"] for m in open_markets)
    year = int((event.get("endDate") or "2026")[:4])

    dates = [parse_date(m["groupItemTitle"], year) for m in open_markets]
    if all(dates) and len(set(dates)) == len(dates):
        if DEADLINE.search(questions) and not EXACT.search(event["title"]):
            # "Before a later date" is easier: the negative key puts it first.
            return "fecha", [(-f.toordinal(), m) for f, m in zip(dates, open_markets)]
        return None

    nums = [number(m["groupItemTitle"]) for m in open_markets]
    if all(n is not None for n in nums) and len(set(nums)) == len(nums):
        up, down = bool(UP.search(questions)), bool(DOWN.search(questions))
        if up and not down:
            return "umbral_arriba", [(n, m) for n, m in zip(nums, open_markets)]
        if down and not up:
            return "umbral_abajo", [(-n, m) for n, m in zip(nums, open_markets)]
    return None


def fee(m, p):
    rate = (m.get("feeSchedule") or {}).get("rate") or 0
    return rate * p * (1 - p)


def pairs(kind, markets):
    """Pairs (easy, hard): the Yes of the hard one implies the Yes of the easy one."""
    ordered = sorted(markets, key=lambda km: km[0])
    for (_, easy), (_, hard) in combinations(ordered, 2):
        ask_yes_easy = float(easy["bestAsk"])
        ask_no_hard = 1 - float(hard["bestBid"])
        cost = ask_yes_easy + ask_no_hard
        net = cost + fee(easy, ask_yes_easy) + fee(hard, ask_no_hard)
        yield easy, hard, cost, net


def book(token):
    req = urllib.request.Request(
        f"https://clob.polymarket.com/book?token_id={token}",
        headers={"User-Agent": "polyquack-sondeo/0.1"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def depth(easy, hard):
    """Shares of the pair that can be bought at net cost < 1, walking both order books."""
    asks_yes = sorted(
        (float(a["price"]), float(a["size"]))
        for a in book(json.loads(easy["clobTokenIds"])[0])["asks"]
    )
    asks_no = sorted(
        (float(a["price"]), float(a["size"]))
        for a in book(json.loads(hard["clobTokenIds"])[1])["asks"]
    )
    total = profit = 0.0
    i = j = 0
    while i < len(asks_yes) and j < len(asks_no):
        (p1, s1), (p2, s2) = asks_yes[i], asks_no[j]
        net = p1 + p2 + fee(easy, p1) + fee(hard, p2)
        if net >= 1:
            break
        q = min(s1, s2)
        total += q
        profit += q * (1 - net)
        asks_yes[i] = (p1, s1 - q)
        asks_no[j] = (p2, s2 - q)
        i += asks_yes[i][1] <= 1e-9
        j += asks_no[j][1] <= 1e-9
    return total, profit


def main():
    data = json.loads((HERE / "eventos.json").read_text())
    events = data["eventos"]
    ladders = [(e, *c) for e in events for c in ladders_of(e)]
    by_kind = {}
    everything = []
    for e, kind, markets in ladders:
        by_kind[kind] = by_kind.get(kind, 0) + 1
        for easy, hard, cost, net in pairs(kind, markets):
            everything.append(
                {
                    "evento": e["title"],
                    "tipo": kind,
                    "facil": easy["question"],
                    "dificil": hard["question"],
                    "costo": round(cost, 4),
                    "neto": round(net, 4),
                    "_f": easy,
                    "_d": hard,
                }
            )

    violations = sorted((p for p in everything if p["neto"] < 1), key=lambda p: p["neto"])
    for p in violations[:40]:
        try:
            p["acciones"], p["ganancia_usd"] = depth(p["_f"], p["_d"])
        except Exception as ex:  # noqa: BLE001 - probe
            p["error_libro"] = str(ex)

    random.seed(7)
    sample = random.sample(everything, min(60, len(everything)))
    clean = lambda p: {k: v for k, v in p.items() if not k.startswith("_")}  # noqa: E731
    summary = {
        "descargado": data["descargado"],
        "eventos_activos": len(events),
        "eventos_negRisk": sum(bool(e.get("negRisk")) for e in events),
        "escaleras_por_tipo": by_kind,
        "pares": len(everything),
        "pares_costo_bruto_menor_1": sum(p["costo"] < 1 for p in everything),
        "pares_neto_menor_1": len(violations),
    }
    (HERE / "resultado.json").write_text(
        json.dumps(
            {
                "resumen": summary,
                "violaciones": [clean(p) for p in violations[:40]],
                "muestra_para_etiquetar": [clean(p) for p in sample],
            },
            indent=1,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=1))
    for p in violations[:15]:
        print(
            round(p["neto"], 3),
            p.get("acciones"),
            p.get("ganancia_usd"),
            "|",
            p["facil"],
            "=>",
            p["dificil"],
        )


if __name__ == "__main__":
    sys.exit(main())
