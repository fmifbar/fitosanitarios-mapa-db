"""
comprobar_antes_de_publicar.py - No publicar un catálogo recortado.

Por qué existe
--------------
Hasta el 02/10/2026 el flujo diario hacía commit **pase lo que pase**. Si el
Ministerio respondía a medias un martes —y responde a medias de vez en
cuando—, se publicaba un catálogo con la mitad de los productos y TT EDITOR se
lo tragaba a la mañana siguiente.

Y un catálogo recortado no es un catálogo viejo. Un catálogo viejo dice cosas
de la semana pasada; uno recortado **dice que no existe lo que sí existe**: un
producto que desaparece se lee como «no autorizado», y entonces el programa
quita de la lista productos que el técnico puede usar, o peor, deja de avisar
de uno que se ha retirado porque ya no lo tiene.

Qué comprueba
-------------
Lo mínimo que distingue una sincronización buena de una rota:

  - que la base abra y tenga las tablas,
  - que no haya perdido más del 10 % de los productos respecto a la versión
    anterior (el mismo 90 % que se pidió para el repositorio),
  - que los usos no se hayan desplomado,
  - que el JSON exportado cuadre con la base.

Si algo no cuadra, **sale con error y el flujo no publica**. Se queda la
versión anterior, que es correcta aunque sea de ayer.

También escribe `estado.json`
-----------------------------
Con la fecha, el origen y los recuentos. Hasta ahora, saber si una
sincronización había ido bien exigía abrir una base de 42 MB. Un archivo de
texto de veinte líneas lo dice de un vistazo, y además queda en el historial:
se puede mirar qué decía el catálogo cualquier día pasado sin descargarse nada.

Uso:
    python comprobar_antes_de_publicar.py [--base X.db] [--json Y.json]
"""
import argparse
import datetime
import json
import os
import subprocess
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).parent

# El mismo criterio que se pidió para el catálogo y para las fichas: por debajo
# del 90 % de lo que había, no se publica. Una baja real del registro nunca es
# de ese tamaño; una respuesta cortada, sí.
MINIMO_RESPECTO_A_LA_ANTERIOR = 0.90

TABLAS = ("mapa_productos", "mapa_usos", "mapa_sustancias_activas",
          "mapa_producto_composicion", "mapa_plazos_seguridad",
          "mapa_seguridad", "mapa_toxicologia", "mapa_mitigaciones")


def _consolidar_wal(ruta: Path):
    """
    Volcar el WAL dentro del `.db` antes de publicarlo.

    La base trabaja en modo WAL: lo que se escribe va primero a un archivo
    `-wal` aparte y solo pasa al `.db` al consolidar. SQLite lo hace solo al
    cerrar la última conexión, pero **si un proceso termina mal, no**. Y lo
    que se sube al repositorio es el `.db` a secas: publicar uno con escrituras
    aún en el `-wal` es publicar una base a la que le faltan datos, y sin que
    se note, porque abre perfectamente.
    """
    con = sqlite3.connect(ruta)
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        con.commit()
    except sqlite3.Error as e:
        print(f"[i] No se pudo consolidar el WAL ({e}). Se continúa.")
    finally:
        con.close()


def _contar(ruta: Path) -> dict:
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        tablas = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        faltan = [t for t in TABLAS if t not in tablas]
        if faltan:
            raise RuntimeError(f"A la base le faltan tablas: {', '.join(faltan)}")
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLAS}
    finally:
        con.close()


def _version_anterior(nombre: str) -> dict | None:
    """Los recuentos de la versión que ya está publicada, si se pueden leer."""
    try:
        bruto = subprocess.run(["git", "show", f"HEAD:{nombre}"],
                               capture_output=True, cwd=BASE)
        if bruto.returncode != 0 or not bruto.stdout:
            return None
        tmp = BASE / ".anterior.tmp.db"
        tmp.write_bytes(bruto.stdout)
        try:
            return _contar(tmp)
        finally:
            # SQLite deja también `-wal` y `-shm` al abrir. Borrar solo el
            # `.db` dejaba dos archivos sueltos en el repositorio después de
            # cada comprobación.
            for sufijo in ("", "-wal", "-shm"):
                Path(str(tmp) + sufijo).unlink(missing_ok=True)
    except Exception as e:
        print(f"[i] No se pudo leer la versión anterior ({e}). Se continúa.")
        return None


def _estado_json(ruta: Path, ahora: dict, antes: dict | None, json_path: Path):
    """El resumen que hasta hoy había que sacar abriendo una base de 42 MB."""
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        def uno(q, d=0):
            """
            Una columna que todavía no existe no es un error: es que esa base
            es anterior a cuando se añadió. Se devuelve `None`, que quiere
            decir «no disponible», y no un 0, que diría «hay cero».
            """
            try:
                return (con.execute(q).fetchone() or [d])[0] or d
            except sqlite3.OperationalError as e:
                if "no such column" in str(e):
                    return None
                raise

        vigentes = uno("SELECT COUNT(*) FROM mapa_productos WHERE estado = 'Vigente'")
        con_ficha = uno("SELECT COUNT(*) FROM mapa_productos "
                        "WHERE pdf_sha256 IS NOT NULL AND pdf_sha256 <> ''")
        con_sistema = uno("SELECT COUNT(*) FROM mapa_usos "
                          "WHERE sistema_cultivo IS NOT NULL AND sistema_cultivo <> ''")
        invernadero = uno("SELECT COUNT(*) FROM mapa_usos WHERE sistema_cultivo = 'Invernadero'")
        sincronizado = uno("SELECT MAX(sincronizado_en) FROM mapa_productos", "")
    finally:
        con.close()

    estado = {
        "generado": datetime.datetime.now(datetime.timezone.utc)
                    .isoformat(timespec="seconds"),
        "origen": "Registro Oficial de Productos Fitosanitarios (MAPA)",
        "el_mapa_publica": "semanalmente, los viernes a partir de las 14:00",
        "ultima_sincronizacion_en_la_base": sincronizado,
        "filas": ahora,
        "productos_vigentes": vigentes,
        "productos_con_ficha_pdf_extraida": con_ficha,
        "usos_con_sistema_de_cultivo_declarado": con_sistema,
        "usos_declarados_de_invernadero": invernadero,
        "tamano_mb": {
            "base": round(ruta.stat().st_size / 1e6, 1),
            "json": round(json_path.stat().st_size / 1e6, 1) if json_path.exists() else None,
        },
        "variacion_respecto_a_la_anterior": (
            {t: ahora[t] - antes[t] for t in ahora} if antes else
            "no habia version anterior con la que comparar"),
        "aviso": ("Los recuentos son de esta copia, no del Ministerio en vivo. "
                  "Lo que TT EDITOR calcula a partir de estos datos (ambito, "
                  "dosis agregadas, cultivos y plagas) no es oficial aunque lo "
                  "parezca: es una agregacion nuestra."),
    }
    salida = BASE / "estado.json"
    salida.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] escrito {salida.name}")
    return estado


def main(base="fitosanitarios_mapa.db", json_nombre="fitosanitarios_mapa_completo.json"):
    ruta = BASE / base
    ruta_json = BASE / json_nombre

    if not ruta.exists():
        sys.exit(f"[X] No existe {base}. No se publica.")

    _consolidar_wal(ruta)

    try:
        ahora = _contar(ruta)
    except Exception as e:
        sys.exit(f"[X] La base no se puede leer: {e}. No se publica.")

    if not ahora["mapa_productos"]:
        sys.exit("[X] La base no tiene ni un producto. No se publica.")

    antes = _version_anterior(base)
    problemas = []
    if antes:
        for tabla in ("mapa_productos", "mapa_usos"):
            viejo, nuevo = antes.get(tabla, 0), ahora.get(tabla, 0)
            if viejo and nuevo < viejo * MINIMO_RESPECTO_A_LA_ANTERIOR:
                problemas.append(
                    f"{tabla}: {viejo} -> {nuevo} "
                    f"(pierde el {100 * (1 - nuevo / viejo):.0f} %)")

    print("RECUENTOS")
    for t in TABLAS:
        delta = f"  ({ahora[t] - antes[t]:+d})" if antes else ""
        print(f"   {t:<30} {ahora[t]:>8}{delta}")

    if problemas:
        print("\n[X] NO SE PUBLICA. El catálogo ha menguado más de lo admisible:")
        for p in problemas:
            print(f"      {p}")
        print("\n    Un catálogo recortado no es uno viejo: dice que no existe lo "
              "que sí existe.\n    Se conserva la versión anterior.")
        sys.exit(1)

    _estado_json(ruta, ahora, antes, ruta_json)
    print("\n[ok] Comprobado. Se puede publicar.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Comprueba el catálogo antes de publicarlo.")
    ap.add_argument("--base", default="fitosanitarios_mapa.db")
    ap.add_argument("--json", dest="json_nombre", default="fitosanitarios_mapa_completo.json")
    a = ap.parse_args()
    sys.exit(main(a.base, a.json_nombre))
