"""
medir_condiciones_invernadero.py - Cuantos usos dan condiciones distintas bajo plastico.

El problema
-----------
Las columnas de un uso —dosis, plazo de seguridad, volumen de caldo— traen a
menudo **las condiciones de aire libre**, y las de invernadero van escritas en
el texto de condicionamiento especifico.

El caso que lo destapo, APHOX (registro 11826) en tomate:

    columnas:      dosis 0,1 %      plazo 3 dias
    condiciones:   «En invernadero la dosis sera de 0,05 % con un maximo de
                    600 l/ha de caldo y un PS de 7 dias.»

Un tecnico de Murgiverde que se fie de las columnas aplicaria **el doble de
dosis** y esperaria **menos de la mitad del plazo** antes de recolectar. Y en
Murgiverde todo es invernadero.

Esto cuenta cuantas veces pasa, para saber si merece la pena avisar y de que
tamaño es el aviso.

Uso:
    python medir_condiciones_invernadero.py [base.db]
"""
import collections
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

BASE = Path(__file__).parent

NUESTROS = ("tomate", "pimiento", "berenjena", "pepino", "calabacin",
            "melon", "sandia", "solanacea", "cucurbitacea")

RX_INVERNADERO = re.compile(r"(?<![a-z])invernadero", re.I)
RX_DOSIS = re.compile(r"\d+[,.]?\d*\s*(?:%|l/ha|kg/ha|cc/l|g/l|ml/l)", re.I)
RX_PLAZO = re.compile(r"(?:\bps\b|plazo de seguridad|plazo)\D{0,12}\d+\s*d", re.I)


def llano(t):
    s = unicodedata.normalize("NFKD", str(t or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def es_nuestro(cultivo):
    return any(n in llano(cultivo) for n in NUESTROS)


def main(ruta=None):
    ruta = Path(ruta or BASE / "fitosanitarios_mapa.db")
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        filas = con.execute(
            "SELECT cultivo_nombre, sistema_cultivo, condiciones_especificas "
            "FROM mapa_usos").fetchall()
    finally:
        con.close()

    c = collections.Counter()
    for f in filas:
        if not es_nuestro(f["cultivo_nombre"]):
            continue
        c["usos de nuestros cultivos"] += 1
        cond = f["condiciones_especificas"] or ""
        if not RX_INVERNADERO.search(cond):
            continue
        c["  mencionan invernadero en las condiciones"] += 1
        dosis, plazo = bool(RX_DOSIS.search(cond)), bool(RX_PLAZO.search(cond))
        if dosis:
            c["    y dan una dosis en el texto"] += 1
        if plazo:
            c["    y dan un plazo en el texto"] += 1
        # El caso grave: el campo no declara invernadero —asi que las
        # columnas son de otra cosa— pero el texto si da condiciones para el.
        if not (f["sistema_cultivo"] or "").strip() and (dosis or plazo):
            c["  GRAVE: sin declarar y con condiciones en el texto"] += 1

    ancho = max(len(k) for k in c) if c else 10
    for k, v in c.items():
        print(f"{k:<{ancho}} {v:>7}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
