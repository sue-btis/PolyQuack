"""Control de selección para el sondeo E1: elegir monedas con la primera mitad y medir en la segunda.

Con 38 monedas y 4 umbrales, las mejores del total salen favorecidas por suerte. Aquí la regla
"quedarse con las 10 monedas de mayor diferencia en la primera mitad" se decide sin ver la segunda.
"""

import json
import statistics
from pathlib import Path

from sondeo import CACHE, COMISION_HL, COMISION_PM, por_hora, simular

UMBRAL = 0.00001
resultado = {}
monedas = {}
for archivo in sorted(CACHE.glob("pm_*.json")):
    moneda = archivo.stem[3:]
    hl_archivo = CACHE / f"hl_{moneda}.json"
    if not hl_archivo.exists():
        continue
    pm = por_hora(json.loads(archivo.read_text()), "timestamp", "funding_rate")
    hl = por_hora(json.loads(hl_archivo.read_text()), "time", "fundingRate")
    horas = sorted(set(pm) & set(hl))
    if len(horas) < 24 * 14:
        continue
    monedas[moneda] = (horas, {h: pm[h] - hl[h] for h in horas})

# Corte común por fecha, no por moneda, para que ninguna mitad vea el futuro de otra.
todas = sorted({h for horas, _ in monedas.values() for h in horas})
corte = todas[len(todas) // 2]


def neto_anual(horas, dif):
    if len(horas) < 48:
        return None
    cobrado, comisiones, _ = simular(horas, dif, UMBRAL)
    return (cobrado - comisiones) * 365 * 24 / len(horas)


primera = {m: statistics.mean(d[h] for h in hs if h < corte) for m, (hs, d) in monedas.items()}
elegidas = sorted(primera, key=lambda m: -abs(primera[m]))[:10]
segunda = {m: neto_anual([h for h in hs if h >= corte], d) for m, (hs, d) in monedas.items()}
segunda = {m: v for m, v in segunda.items() if v is not None}

resumen = {
    "monedas": len(monedas),
    "corte_utc_hora": corte,
    "comision_ida_vuelta_dos_patas": 2 * (COMISION_PM + COMISION_HL),
    "elegidas_primera_mitad": elegidas,
    "neto_anual_segunda_mitad_elegidas_promedio": statistics.mean(
        segunda[m] for m in elegidas if m in segunda
    ),
    "neto_anual_segunda_mitad_todas_promedio": statistics.mean(segunda.values()),
    "neto_anual_segunda_mitad_por_moneda": {
        m: round(segunda[m], 4) for m in elegidas if m in segunda
    },
    "dif_media_anual_todas": statistics.mean(
        statistics.mean(d.values()) for _, d in monedas.values()
    )
    * 24
    * 365,
    "monedas_con_dif_negativa": sum(statistics.mean(d.values()) < 0 for _, d in monedas.values()),
}
(Path(__file__).parent / "fuera_de_muestra.json").write_text(
    json.dumps(resumen, indent=1), encoding="utf-8"
)
print(json.dumps(resumen, indent=1))
