"""Sondeo E1: ¿la tasa de funding de Polymarket Perps se separa de la de Hyperliquid lo
suficiente para cobrar la diferencia con una posición neutral? (desechable)

Ambas plataformas cobran funding cada hora. Estrategia simulada, walk-forward por día:
si la diferencia promedio de las 24 h previas supera un umbral, se mantiene por las 24 h
siguientes la posición que cobra (corto donde la tasa es mayor, largo donde es menor).
Comisión de taker al abrir y al cerrar en las dos patas. No modela el riesgo de base
(que los dos precios se separen) ni liquidaciones.
"""

import json
import statistics
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

AQUI = Path(__file__).parent
CACHE = AQUI / "cache"
CACHE.mkdir(exist_ok=True)
UA = {"User-Agent": "polyquack-sondeo/0.1"}
INICIO_MS = int(datetime(2026, 9, 3, tzinfo=UTC).timestamp() * 1000)
FIN_MS = int(datetime(2026, 10, 26, tzinfo=UTC).timestamp() * 1000)
# Nivel base de cada plataforma (cuenta nueva), leído de su documentación el 26 oct 2026.
COMISION_PM = 0.0004
COMISION_HL = 0.00045
# Umbrales por hora: 0.00001 por hora son 8.8 % al año.
UMBRALES = (0.0, 0.000005, 0.00001, 0.00002)


def http(url, cuerpo=None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cabeceras = dict(UA, **({"Content-Type": "application/json"} if cuerpo is not None else {}))
    req = urllib.request.Request(url, data=datos, headers=cabeceras)
    for espera in (2, 5, 15, 30):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(espera)
    raise RuntimeError(f"429 persistente en {url}")


def cacheado(nombre, funcion):
    archivo = CACHE / nombre
    if archivo.exists():
        return json.loads(archivo.read_text())
    datos = funcion()
    archivo.write_text(json.dumps(datos))
    return datos


def funding_pm(instrument_id):
    # La API devuelve de lo más nuevo a lo más viejo, 100 por página: se pagina hacia atrás.
    filas, hasta = [], FIN_MS
    while True:
        r = http(
            f"https://api.perpetuals.polymarket.com/v1/info/funding?instrument_id={instrument_id}"
            f"&start_timestamp={INICIO_MS}&end_timestamp={hasta}"
        )
        filas += r["data"]
        if not r.get("more") or not r["data"]:
            return filas
        hasta = min(f["timestamp"] for f in r["data"]) - 1
        time.sleep(0.8)


def funding_hl(moneda):
    filas, desde = [], INICIO_MS
    while desde < FIN_MS:
        r = http(
            "https://api.hyperliquid.xyz/info",
            {"type": "fundingHistory", "coin": moneda, "startTime": desde, "endTime": FIN_MS},
        )
        if not r:
            break
        filas += r
        desde = max(f["time"] for f in r) + 1
        time.sleep(0.8)
    return filas


def por_hora(filas, campo_t, campo_r):
    return {int(f[campo_t]) // 3_600_000: float(f[campo_r]) for f in filas}


def simular(horas, dif, umbral):
    """dif[h] = tasa PM − tasa HL. Lado +1: corto PM / largo HL cobra dif; lado −1 cobra −dif."""
    cobrado = comisiones = 0.0
    lado = 0
    horas_en_posicion = 0
    for i in range(24, len(horas), 24):
        previo = statistics.mean(dif[h] for h in horas[i - 24 : i])
        nuevo = 0 if abs(previo) <= umbral else (1 if previo > 0 else -1)
        if nuevo != lado:
            # Cerrar y abrir: cada cambio cuesta las dos patas una vez por operación.
            operaciones = (1 if lado else 0) + (1 if nuevo else 0)
            comisiones += operaciones * (COMISION_PM + COMISION_HL)
            lado = nuevo
        for h in horas[i : i + 24]:
            if lado:
                cobrado += lado * dif[h]
                horas_en_posicion += 1
    if lado:
        comisiones += COMISION_PM + COMISION_HL
    return cobrado, comisiones, horas_en_posicion


def main():
    instrumentos = cacheado(
        "instrumentos.json",
        lambda: http("https://api.perpetuals.polymarket.com/v1/info/instruments"),
    )
    meta_hl = cacheado(
        "meta_hl.json", lambda: http("https://api.hyperliquid.xyz/info", {"type": "meta"})
    )
    monedas_hl = {a["name"] for a in meta_hl["universe"]}
    cripto = [
        i for i in instrumentos if i.get("category") == "crypto" and i["base_asset"] in monedas_hl
    ]
    resultados = []
    for inst in cripto:
        moneda = inst["base_asset"]
        pm = por_hora(
            cacheado(f"pm_{moneda}.json", lambda: funding_pm(inst["instrument_id"])),
            "timestamp",
            "funding_rate",
        )
        hl = por_hora(
            cacheado(f"hl_{moneda}.json", lambda: funding_hl(moneda)), "time", "fundingRate"
        )
        horas = sorted(set(pm) & set(hl))
        if len(horas) < 24 * 7:
            continue
        dif = {h: pm[h] - hl[h] for h in horas}
        valores = list(dif.values())
        fila = {
            "moneda": moneda,
            "horas": len(horas),
            "pm_media_anual": statistics.mean(pm[h] for h in horas) * 24 * 365,
            "hl_media_anual": statistics.mean(hl[h] for h in horas) * 24 * 365,
            "dif_media_anual": statistics.mean(valores) * 24 * 365,
            "dif_abs_media_anual": statistics.mean(abs(v) for v in valores) * 24 * 365,
            "horas_pm_mayor": sum(v > 0 for v in valores) / len(valores),
        }
        dias = len(horas) / 24
        for u in UMBRALES:
            cobrado, comisiones, en_pos = simular(horas, dif, u)
            neto = cobrado - comisiones
            fila[f"neto_anual_u{u}"] = neto * 365 / dias
            fila[f"en_posicion_u{u}"] = en_pos / len(horas)
        resultados.append(fila)
        print(
            moneda,
            len(horas),
            "h",
            "dif media anual",
            f"{fila['dif_media_anual']:+.1%}",
            "neto (u=0.00001)",
            f"{fila['neto_anual_u1e-05']:+.1%}",
            flush=True,
        )

    resultados.sort(key=lambda f: -f["neto_anual_u1e-05"])
    (AQUI / "resultado.json").write_text(json.dumps(resultados, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
