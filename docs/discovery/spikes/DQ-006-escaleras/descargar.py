"""Descarga los eventos activos de Gamma a eventos.json, solo con los campos del sondeo (desechable)."""

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

# El listado con offset se corta en 2,500; el keyset no tiene ese tope.
BASE = "https://gamma-api.polymarket.com/events/keyset?closed=false&active=true&limit=500"
CAMPOS_EVENTO = ("id", "slug", "title", "negRisk", "endDate")
CAMPOS_MERCADO = (
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


def recortar(evento):
    corto = {k: evento.get(k) for k in CAMPOS_EVENTO}
    corto["markets"] = [{k: m.get(k) for k in CAMPOS_MERCADO} for m in evento.get("markets", [])]
    return corto


eventos = []
cursor = None
while True:
    url = BASE + (f"&after_cursor={urllib.parse.quote(cursor)}" if cursor else "")
    with urllib.request.urlopen(url, timeout=60) as r:
        pagina = json.load(r)
    eventos.extend(recortar(e) for e in pagina["events"])
    print(len(eventos), "eventos", flush=True)
    cursor = pagina.get("next_cursor")
    if not cursor or not pagina["events"]:
        break
    time.sleep(0.3)

salida = Path(__file__).with_name("eventos.json")
salida.write_text(
    json.dumps(
        {"descargado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "eventos": eventos}
    )
)
print(len(eventos), "eventos,", sum(len(e["markets"]) for e in eventos), "mercados")
