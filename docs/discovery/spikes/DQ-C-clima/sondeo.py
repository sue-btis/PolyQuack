"""Sondeo C: ¿un pronóstico público corregido le gana al mercado de temperatura máxima?

Desechable. Compara, en mercados ya resueltos, la probabilidad del mercado contra la de un
modelo simple (pronóstico ECMWF de un día antes + sesgo y dispersión aprendidos solo con días
anteriores). Usa precios intermedios cada 3 h, no precios ejecutables: mide si hay información
de más, no ventaja neta (CR-001).
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

AQUI = Path(__file__).parent
CACHE = AQUI / "cache"
CACHE.mkdir(exist_ok=True)

# Estación de resolución de cada ciudad, leída de la descripción de sus mercados.
CIUDADES = {
    "nyc": {"lat": 40.7769, "lon": -73.8740, "tz": "America/New_York", "unidad": "fahrenheit"},
    "london": {"lat": 51.5048, "lon": 0.0495, "tz": "Europe/London", "unidad": "celsius"},
}
MESES = [
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


def get_json(url, nombre):
    archivo = CACHE / nombre
    if archivo.exists():
        return json.loads(archivo.read_text())
    # La Data API responde 403 a clientes sin User-Agent.
    peticion = urllib.request.Request(url, headers={"User-Agent": "polyquack-sondeo/0.1"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(peticion, timeout=60) as r:
                datos = json.load(r)
            archivo.write_text(json.dumps(datos))
            time.sleep(0.2)
            return datos
        except Exception as e:  # noqa: BLE001 - sondeo, se reporta y se reintenta
            print("  error", url[:80], e, file=sys.stderr)
            time.sleep(2)
    return None


def evento(ciudad, dia):
    slug = f"highest-temperature-in-{ciudad}-on-{MESES[dia.month - 1]}-{dia.day}-{dia.year}"
    datos = get_json(f"https://gamma-api.polymarket.com/events?slug={slug}", f"ev_{slug}.json")
    return datos[0] if datos else None


def rango(titulo):
    """'56-57°F' -> (56, 57); '55°F or below' -> (-inf, 55); '74°F or higher' -> (74, inf)."""
    # El guion de "78-79" separa el rango; solo es signo si no lo precede un dígito ("-2°C").
    nums = [int(n) for n in re.findall(r"(?<!\d)-?\d+", titulo)]
    if "below" in titulo:
        return (-math.inf, nums[0])
    if "higher" in titulo or "above" in titulo:
        return (nums[0], math.inf)
    if len(nums) == 2:
        return (nums[0], nums[1])
    return (nums[0], nums[0])


def precio_en(token, instante):
    datos = get_json(
        f"https://data-api.polymarket.com/v2/prices-history?token_id={token}&interval=max&bucket_seconds=10800",
        f"ph_{token[:24]}.json",
    )
    if not datos or not datos.get("data"):
        return None
    previos = [p for p in datos["data"] if p["timestamp"] <= instante]
    return previos[-1]["price"] if previos else None


def pronostico(ciudad, dia):
    c = CIUDADES[ciudad]
    url = (
        "https://previous-runs-api.open-meteo.com/v1/forecast?"
        f"latitude={c['lat']}&longitude={c['lon']}&start_date={dia}&end_date={dia}"
        f"&hourly=temperature_2m_previous_day1&temperature_unit={c['unidad']}"
        f"&timezone={c['tz']}&models=ecmwf_ifs025"
    )
    datos = get_json(url, f"fc_{ciudad}_{dia}.json")
    valores = [
        v
        for v in (datos or {}).get("hourly", {}).get("temperature_2m_previous_day1", [])
        if v is not None
    ]
    return max(valores) if len(valores) >= 20 else None


def prob_rango(lo, hi, mu, sigma):
    # La estación reporta grados enteros: el rango [lo, hi] cubre [lo - 0.5, hi + 0.5).
    cdf = lambda x: 0.5 * (1 + math.erf((x - mu) / (sigma * math.sqrt(2))))  # noqa: E731
    return cdf(hi + 0.5) - cdf(lo - 0.5)


def main():
    ciudad = sys.argv[1]
    dias = int(sys.argv[2])
    hoy = date(2026, 10, 24)
    filas = []
    for k in range(dias, 0, -1):
        dia = hoy - timedelta(days=k)
        ev = evento(ciudad, dia)
        if not ev or not ev.get("closed"):
            continue
        fc = pronostico(ciudad, dia)
        if fc is None:
            continue
        # Foto del mercado a las 16:00 UTC del día anterior (mediodía en Nueva York).
        instante = (
            int(datetime(dia.year, dia.month, dia.day, 16, tzinfo=UTC).timestamp()) - 86400
        )
        opciones = []
        for m in ev["markets"]:
            gano = json.loads(m["outcomePrices"])[0] == "1"
            token = json.loads(m["clobTokenIds"])[0]
            opciones.append(
                {
                    "rango": rango(m["groupItemTitle"]),
                    "gano": gano,
                    "precio": precio_en(token, instante),
                    "tasa": (m.get("feeSchedule") or {}).get("rate"),
                }
            )
        if sum(o["gano"] for o in opciones) != 1 or any(o["precio"] is None for o in opciones):
            continue
        ganador = next(o for o in opciones if o["gano"])
        filas.append({"dia": str(dia), "fc": fc, "opciones": opciones, "ganador": ganador["rango"]})
        print(dia, "pronóstico", round(fc, 1), "ganó", ganador["rango"], flush=True)

    (AQUI / f"filas_{ciudad}.json").write_text(json.dumps(filas, default=str))
    evaluar(ciudad, filas)


def evaluar(ciudad, filas):
    """Walk-forward: el sesgo y la dispersión de cada día se aprenden solo con días anteriores."""
    errores = []
    res = []
    calentamiento = 14
    for f in filas:
        lo, hi = f["ganador"]
        centro = hi if lo == -math.inf else lo if hi == math.inf else (lo + hi) / 2
        if len(errores) >= calentamiento:
            sesgo = statistics.mean(errores)
            sigma = max(statistics.stdev(errores), 0.8)
            mu = f["fc"] + sesgo
            suma_mercado = sum(o["precio"] for o in f["opciones"])
            b_mod = b_mer = b_mez = 0.0
            ll_mod = ll_mer = 0.0
            for o in f["opciones"]:
                p_mod = prob_rango(*o["rango"], mu, sigma)
                p_mer = o["precio"] / suma_mercado
                # Si la mezcla le gana al mercado solo, el pronóstico trae información que el precio no tiene.
                p_mez = 0.8 * p_mer + 0.2 * p_mod
                y = 1.0 if o["gano"] else 0.0
                b_mod += (p_mod - y) ** 2
                b_mer += (p_mer - y) ** 2
                b_mez += (p_mez - y) ** 2
                if o["gano"]:
                    ll_mod = -math.log(max(p_mod, 1e-6))
                    ll_mer = -math.log(max(p_mer, 1e-6))
            res.append(
                {
                    "dia": f["dia"],
                    "brier_modelo": b_mod,
                    "brier_mercado": b_mer,
                    "brier_mezcla": b_mez,
                    "log_modelo": ll_mod,
                    "log_mercado": ll_mer,
                    "suma_mercado": suma_mercado,
                }
            )
        # El centro del rango ganador aproxima la máxima real (la estación da enteros).
        errores.append(centro - f["fc"])

    if not res:
        print("sin días evaluables")
        return
    n = len(res)
    resumen = {
        "ciudad": ciudad,
        "dias_evaluados": n,
        "brier_modelo": statistics.mean(r["brier_modelo"] for r in res),
        "brier_mercado": statistics.mean(r["brier_mercado"] for r in res),
        "brier_mezcla_80_20": statistics.mean(r["brier_mezcla"] for r in res),
        "log_modelo": statistics.mean(r["log_modelo"] for r in res),
        "log_mercado": statistics.mean(r["log_mercado"] for r in res),
        "dias_modelo_mejor_brier": sum(r["brier_modelo"] < r["brier_mercado"] for r in res),
        "suma_mercado_media": statistics.mean(r["suma_mercado"] for r in res),
    }
    (AQUI / f"resumen_{ciudad}.json").write_text(
        json.dumps({"resumen": resumen, "dias": res}, indent=1)
    )
    print(json.dumps(resumen, indent=1))


if __name__ == "__main__":
    main()
