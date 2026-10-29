"""Sondeo B: escaleras por plantilla en mercados activos (desechable).

Una escalera es un evento cuyos mercados solo cambian un umbral ("arriba de X") o una fecha
límite ("antes de X"). Si A implica B, comprar Sí de B y No de A paga al menos 1 en cualquier
resultado; hay oportunidad cuando el costo ejecutable de ese par, con comisión de taker, es < 1.
"""

import json
import random
import re
import sys
import urllib.request
from datetime import date
from itertools import combinations
from pathlib import Path

AQUI = Path(__file__).parent
MESES = {
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
MESES.update({m[:3]: i for m, i in list(MESES.items())})

SUBE = re.compile(
    r"\b(above|over|reach|hit|at least|more than|greater than|exceed|higher than|or more|≥|>)", re.I
)
BAJA = re.compile(r"\b(below|under|dip|less than|lower than|fall to|drop to|or less|≤|<)", re.I)
LIMITE = re.compile(r"\b(by|before|until|no later than)\b", re.I)
EXACTO = re.compile(r"\b(on|in|during)\s+(the\s+)?(" + "|".join(MESES) + r")\b", re.I)


def numero(texto):
    t = texto.replace(",", "")
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*([kmb])?\b", t, re.I)
    if not m:
        return None
    escala = {"k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(2) or "").lower(), 1)
    return float(m.group(1)) * escala


def fecha(texto, anio_evento):
    m = re.search(r"(" + "|".join(MESES) + r")[a-z]*\.?\s+(\d{1,2})(?:,?\s*(\d{4}))?", texto, re.I)
    if not m:
        return None
    anio = int(m.group(3)) if m.group(3) else anio_evento
    try:
        return date(anio, MESES[m.group(1).lower()[:3]], int(m.group(2)))
    except ValueError:
        return None


def abiertos(evento):
    return [
        m
        for m in evento["markets"]
        if not m["closed"]
        and m.get("acceptingOrders")
        and m.get("bestAsk") is not None
        and m.get("bestBid") is not None
        and m.get("groupItemTitle")
    ]


ARRIBA_EXPLICITO = re.compile(
    r"\(HIGH\)|or (higher|more|above)|\babove\b|\bover\b|greater than|more than|at least|≥|>", re.I
)
ABAJO_EXPLICITO = re.compile(
    r"\(LOW\)|or (lower|less|below)|\bbelow\b|\bunder\b|less than|fewer than|≤|<", re.I
)


def sentido(pregunta):
    """'arriba', 'abajo' o None. "hit X" o "reach X" sin más es ambiguo: depende del valor actual."""
    arriba, abajo = bool(ARRIBA_EXPLICITO.search(pregunta)), bool(ABAJO_EXPLICITO.search(pregunta))
    return "arriba" if arriba and not abajo else "abajo" if abajo and not arriba else None


def escaleras_de(evento):
    """Agrupa por sentido explícito de cada mercado; un evento puede tener dos escaleras opuestas."""
    if evento.get("negRisk"):
        return []
    mercados = abiertos(evento)
    if len(mercados) < 2:
        return []
    c = clasificar_fecha(evento, mercados)
    if c:
        return [c]
    resultado = []
    for lado, tipo, signo in (("arriba", "umbral_arriba", 1), ("abajo", "umbral_abajo", -1)):
        grupo = [m for m in mercados if sentido(m["question"]) == lado]
        nums = [numero(m["groupItemTitle"]) for m in grupo]
        if len(grupo) >= 2 and None not in nums and len(set(nums)) == len(nums):
            resultado.append((tipo, [(signo * n, m) for n, m in zip(nums, grupo)]))
    return resultado


def clasificar_fecha(evento, abiertos):
    fechas = []
    for m in abiertos:
        # El endDate del evento no siempre cubre a todos sus mercados; el de cada mercado sí.
        # Se elige el año que deja la fecha más cerca del cierre del mercado (31 dic cierra 1 ene UTC).
        cierre = date.fromisoformat((m.get("endDate") or "2026-12-31")[:10])
        candidatos = [fecha(m["groupItemTitle"], cierre.year + d) for d in (-1, 0, 1)]
        candidatos = [f for f in candidatos if f]
        fechas.append(min(candidatos, key=lambda f: abs((f - cierre).days)) if candidatos else None)
    if not all(fechas) or len(set(fechas)) != len(fechas):
        return None
    preguntas = " ".join(m["question"] for m in abiertos)
    if LIMITE.search(preguntas) and not EXACTO.search(evento["title"]):
        return "fecha", [(-f.toordinal(), m) for f, m in zip(fechas, abiertos)]
    return None


def clasificar(evento, abiertos):
    """Devuelve (tipo, [(clave, mercado)]) o None. La clave ordena del Sí más fácil al más difícil."""
    if len(abiertos) < 2:
        return None
    preguntas = " ".join(m["question"] for m in abiertos)
    anio = int((evento.get("endDate") or "2026")[:4])

    fechas = [fecha(m["groupItemTitle"], anio) for m in abiertos]
    if all(fechas) and len(set(fechas)) == len(fechas):
        if LIMITE.search(preguntas) and not EXACTO.search(evento["title"]):
            # "Antes de una fecha posterior" es más fácil: la clave negativa la pone primero.
            return "fecha", [(-f.toordinal(), m) for f, m in zip(fechas, abiertos)]
        return None

    nums = [numero(m["groupItemTitle"]) for m in abiertos]
    if all(n is not None for n in nums) and len(set(nums)) == len(nums):
        sube, baja = bool(SUBE.search(preguntas)), bool(BAJA.search(preguntas))
        if sube and not baja:
            return "umbral_arriba", [(n, m) for n, m in zip(nums, abiertos)]
        if baja and not sube:
            return "umbral_abajo", [(-n, m) for n, m in zip(nums, abiertos)]
    return None


def comision(m, p):
    tasa = (m.get("feeSchedule") or {}).get("rate") or 0
    return tasa * p * (1 - p)


def pares(tipo, mercados):
    """Pares (facil, dificil): el Sí del difícil implica el Sí del fácil."""
    ordenados = sorted(mercados, key=lambda km: km[0])
    for (_, facil), (_, dificil) in combinations(ordenados, 2):
        ask_si_facil = float(facil["bestAsk"])
        ask_no_dificil = 1 - float(dificil["bestBid"])
        costo = ask_si_facil + ask_no_dificil
        neto = costo + comision(facil, ask_si_facil) + comision(dificil, ask_no_dificil)
        yield facil, dificil, costo, neto


def libro(token):
    req = urllib.request.Request(
        f"https://clob.polymarket.com/book?token_id={token}",
        headers={"User-Agent": "polyquack-sondeo/0.1"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def profundidad(facil, dificil):
    """Acciones que se pueden comprar del par con costo neto < 1, caminando los dos libros."""
    asks_si = sorted(
        (float(a["price"]), float(a["size"]))
        for a in libro(json.loads(facil["clobTokenIds"])[0])["asks"]
    )
    asks_no = sorted(
        (float(a["price"]), float(a["size"]))
        for a in libro(json.loads(dificil["clobTokenIds"])[1])["asks"]
    )
    total = ganancia = 0.0
    i = j = 0
    while i < len(asks_si) and j < len(asks_no):
        (p1, s1), (p2, s2) = asks_si[i], asks_no[j]
        neto = p1 + p2 + comision(facil, p1) + comision(dificil, p2)
        if neto >= 1:
            break
        q = min(s1, s2)
        total += q
        ganancia += q * (1 - neto)
        asks_si[i] = (p1, s1 - q)
        asks_no[j] = (p2, s2 - q)
        i += asks_si[i][1] <= 1e-9
        j += asks_no[j][1] <= 1e-9
    return total, ganancia


def main():
    datos = json.loads((AQUI / "eventos.json").read_text())
    eventos = datos["eventos"]
    escaleras = [(e, *c) for e in eventos for c in escaleras_de(e)]
    por_tipo = {}
    todos = []
    for e, tipo, mercados in escaleras:
        por_tipo[tipo] = por_tipo.get(tipo, 0) + 1
        for facil, dificil, costo, neto in pares(tipo, mercados):
            todos.append(
                {
                    "evento": e["title"],
                    "tipo": tipo,
                    "facil": facil["question"],
                    "dificil": dificil["question"],
                    "costo": round(costo, 4),
                    "neto": round(neto, 4),
                    "_f": facil,
                    "_d": dificil,
                }
            )

    violaciones = sorted((p for p in todos if p["neto"] < 1), key=lambda p: p["neto"])
    for p in violaciones[:40]:
        try:
            p["acciones"], p["ganancia_usd"] = profundidad(p["_f"], p["_d"])
        except Exception as ex:  # noqa: BLE001 - sondeo
            p["error_libro"] = str(ex)

    random.seed(7)
    muestra = random.sample(todos, min(60, len(todos)))
    limpiar = lambda p: {k: v for k, v in p.items() if not k.startswith("_")}  # noqa: E731
    resumen = {
        "descargado": datos["descargado"],
        "eventos_activos": len(eventos),
        "eventos_negRisk": sum(bool(e.get("negRisk")) for e in eventos),
        "escaleras_por_tipo": por_tipo,
        "pares": len(todos),
        "pares_costo_bruto_menor_1": sum(p["costo"] < 1 for p in todos),
        "pares_neto_menor_1": len(violaciones),
    }
    (AQUI / "resultado.json").write_text(
        json.dumps(
            {
                "resumen": resumen,
                "violaciones": [limpiar(p) for p in violaciones[:40]],
                "muestra_para_etiquetar": [limpiar(p) for p in muestra],
            },
            indent=1,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(json.dumps(resumen, indent=1))
    for p in violaciones[:15]:
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
