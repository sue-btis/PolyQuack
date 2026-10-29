"""Selection control for probe E1: pick coins with the first half and measure on the second.

With 38 coins and 4 thresholds, the best of the full sample look good by luck. Here the rule
"keep the 10 coins with the largest spread in the first half" is decided without seeing the second.
"""

import json
import statistics
from pathlib import Path

from sondeo import CACHE, HL_FEE, PM_FEE, by_hour, simulate

THRESHOLD = 0.00001
result = {}
coins = {}
for file in sorted(CACHE.glob("pm_*.json")):
    coin = file.stem[3:]
    hl_file = CACHE / f"hl_{coin}.json"
    if not hl_file.exists():
        continue
    pm = by_hour(json.loads(file.read_text()), "timestamp", "funding_rate")
    hl = by_hour(json.loads(hl_file.read_text()), "time", "fundingRate")
    hours = sorted(set(pm) & set(hl))
    if len(hours) < 24 * 14:
        continue
    coins[coin] = (hours, {h: pm[h] - hl[h] for h in hours})

# Common cut by date, not by coin, so neither half sees another coin's future.
all_hours = sorted({h for hours, _ in coins.values() for h in hours})
cutoff = all_hours[len(all_hours) // 2]


def annual_net(hours, spread):
    if len(hours) < 48:
        return None
    collected, fees, _ = simulate(hours, spread, THRESHOLD)
    return (collected - fees) * 365 * 24 / len(hours)


first_half = {m: statistics.mean(d[h] for h in hs if h < cutoff) for m, (hs, d) in coins.items()}
chosen = sorted(first_half, key=lambda m: -abs(first_half[m]))[:10]
second_half = {m: annual_net([h for h in hs if h >= cutoff], d) for m, (hs, d) in coins.items()}
second_half = {m: v for m, v in second_half.items() if v is not None}

summary = {
    "monedas": len(coins),
    "corte_utc_hora": cutoff,
    "comision_ida_vuelta_dos_patas": 2 * (PM_FEE + HL_FEE),
    "elegidas_primera_mitad": chosen,
    "neto_anual_segunda_mitad_elegidas_promedio": statistics.mean(
        second_half[m] for m in chosen if m in second_half
    ),
    "neto_anual_segunda_mitad_todas_promedio": statistics.mean(second_half.values()),
    "neto_anual_segunda_mitad_por_moneda": {
        m: round(second_half[m], 4) for m in chosen if m in second_half
    },
    "dif_media_anual_todas": statistics.mean(
        statistics.mean(d.values()) for _, d in coins.values()
    )
    * 24
    * 365,
    "monedas_con_dif_negativa": sum(statistics.mean(d.values()) < 0 for _, d in coins.values()),
}
(Path(__file__).parent / "fuera_de_muestra.json").write_text(
    json.dumps(summary, indent=1), encoding="utf-8"
)
print(json.dumps(summary, indent=1))
