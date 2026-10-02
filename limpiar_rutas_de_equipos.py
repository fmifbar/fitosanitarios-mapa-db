"""
limpiar_rutas_de_equipos.py - Sacar rutas de equipos de una base publica.

Por que
-------
Este repositorio es **publico**. En `mapa_errores_ingesta` quedaron mensajes
de las ejecuciones del 18/09/2026 con la ruta completa del equipo donde se
corrieron, del tipo `C:\\Users\\<usuario>\\Desktop\\...`. Eso lleva dentro el
nombre de usuario de una persona y la organizacion de su disco.

No es grave —no hay datos de socios ni credenciales— pero en un repositorio
publico sobra, y la norma del proyecto es clara: ahi no sale nada del equipo
ni de la empresa que no haga falta.

Que hace
--------
Sustituye la ruta por el nombre del archivo, que es lo unico que servia para
algo en ese mensaje: saber **que ficha** fallo. La causa del error se conserva
entera.

No borra las filas. Un error registrado es informacion de que paso ese dia, y
borrarlo seria tapar en vez de limpiar.

Uso:
    python limpiar_rutas_de_equipos.py [base.db] [--aplicar]

Sin `--aplicar` solo dice que haria.
"""
import re
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).parent

# Rutas de Windows, de Unix y UNC, **admitiendo espacios dentro**.
#
# La primera version cortaba en el primer espacio, y la ruta de estos mensajes
# es `C:\Users\<usuario>\Desktop\base de datos\cache_pdfs\Ficha_X.pdf`: dejaba
# dentro «base de datos\cache_pdfs\», que es justo lo que se queria quitar.
#
# Se admite el espacio y se corta en el primer archivo con extension, que es
# donde acaban todas estas rutas. Si no hay extension, se corta en el ultimo
# tramo sin espacios, para no tragarse la frase que venga detras.
RUTAS = re.compile(
    r"[A-Za-z]:\\[^\r\n]*?[^\\/\r\n]+\.\w{2,5}"          # C:\...\algo.pdf
    r"|\\\\[^\r\n]*?[^\\/\r\n]+\.\w{2,5}"                 # \\servidor\...\algo.pdf
    r"|/(?:home|Users|mnt|media)/[^\r\n]*?[^/\r\n]+\.\w{2,5}"   # /home/...
    r"|[A-Za-z]:\\[^\s\"']*"                              # C:\sin\extension
    r"|/(?:home|Users|mnt|media)/[^\s\"']*")              # /home/sin/extension


def _acorta(texto: str) -> str:
    """Cambia cada ruta por su ultimo tramo: el nombre del archivo."""
    def solo_nombre(m):
        ruta = m.group(0)
        nombre = re.split(r"[\\/]", ruta.rstrip("\\/"))[-1]
        return nombre or "(ruta omitida)"
    return RUTAS.sub(solo_nombre, texto)


def main(ruta_db=None, aplicar=False):
    ruta = Path(ruta_db or BASE / "fitosanitarios_mapa.db")
    con = sqlite3.connect(ruta)
    try:
        tablas = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "mapa_errores_ingesta" not in tablas:
            print("No hay tabla de errores. Nada que limpiar.")
            return 0

        filas = con.execute(
            "SELECT id, mensaje_error FROM mapa_errores_ingesta "
            "WHERE mensaje_error IS NOT NULL").fetchall()
        cambios = [(i, m, _acorta(m)) for i, m in filas if _acorta(m) != m]

        print(f"filas con una ruta de equipo dentro: {len(cambios)} de {len(filas)}")
        for i, antes, despues in cambios[:3]:
            print(f"\n  id {i}")
            print(f"    antes:   {antes[:110]}")
            print(f"    despues: {despues[:110]}")

        if not cambios:
            return 0
        if aplicar:
            con.executemany("UPDATE mapa_errores_ingesta SET mensaje_error = ? WHERE id = ?",
                            [(d, i) for i, _, d in cambios])
            con.commit()
            print(f"\nAPLICADO: {len(cambios)} mensajes limpiados.")
        else:
            print(f"\nEn seco. Anadir --aplicar para hacerlo.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(main(args[0] if args else None, "--aplicar" in sys.argv))
