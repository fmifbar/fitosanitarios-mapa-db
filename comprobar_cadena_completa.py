"""
comprobar_cadena_completa.py - Pasar un lote de fichas ya extraídas por la cadena.

Para qué
--------
`test_adaptador_canonico.py` comprueba el contrato con una ficha de laboratorio.
Esto lo comprueba con fichas de verdad, que es donde aparecen los casos raros:
composiciones sin cifra, plazos con cuarenta cultivos en una línea, fichas
antiguas sin «Sistema de Cultivo».

No descarga nada ni toca la base del repositorio: monta una base limpia desde
`schema_mapa.sql` en un directorio temporal y cuenta qué ha entrado en cada
tabla. Si una tabla sale a cero, es que una clave no se llama como el ETL
espera, que es el fallo que no da error y se lleva los datos en silencio.

Uso:
    python comprobar_cadena_completa.py <carpeta con fichas/*.json> [cuantas]
"""
import json
import glob
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

from adaptador_canonico import a_canonico
from etl_ingesta_mapa import cargar_producto_en_bd

BASE = Path(__file__).parent
TABLAS = ("mapa_productos", "mapa_usos", "mapa_plazos_seguridad",
          "mapa_sustancias_activas", "mapa_producto_composicion",
          "mapa_seguridad", "mapa_toxicologia", "mapa_mitigaciones")


def base_limpia() -> Path:
    ruta = Path(tempfile.mkdtemp(prefix="comprobacion_fichas_")) / "prueba.db"
    con = sqlite3.connect(ruta)
    try:
        con.executescript((BASE / "schema_mapa.sql").read_text(encoding="utf-8"))
        con.commit()
    finally:
        con.close()
    return ruta


def contar(ruta: Path) -> dict:
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLAS}
    finally:
        con.close()


def rellenos(ruta: Path) -> dict:
    """Cuántas filas tienen de verdad cada campo de las tablas que iban vacías."""
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        out = {}
        for tabla, campos in (
            ("mapa_seguridad", ("seguridad_aplicador", "seguridad_trabajador",
                                "plazo_reentrada", "bandas_seguridad_spe3",
                                "polinizadores_spe8")),
            ("mapa_toxicologia", ("palabra_advertencia", "pictogramas_ghs",
                                  "indicaciones_h", "consejos_p",
                                  "incompatibilidades_mezclas", "gestion_envases")),
            ("mapa_usos", ("ambito", "bbch", "dosis_max", "volumen_caldo_max")),
        ):
            for c in campos:
                out[f"{tabla}.{c}"] = con.execute(
                    f"SELECT COUNT(*) FROM {tabla} WHERE {c} IS NOT NULL AND {c} <> ''"
                ).fetchone()[0]
        return out
    finally:
        con.close()


def main(carpeta: str, cuantas: int = 0):
    ficheros = sorted(glob.glob(os.path.join(carpeta, "*.json")))
    if cuantas:
        ficheros = ficheros[:cuantas]
    if not ficheros:
        sys.exit(f"No hay fichas .json en {carpeta}")

    ruta = base_limpia()
    print(f"base de prueba: {ruta}")
    print(f"fichas:         {len(ficheros)}\n")

    ok = fallos = 0
    errores = []
    for f in ficheros:
        try:
            ficha = json.load(open(f, encoding="utf-8"))
            reg = (ficha.get("producto") or {}).get("num_registro") or \
                Path(f).stem.replace("Ficha_", "")
            cargar_producto_en_bd(a_canonico(ficha, reg), f, db_path=ruta, forzar=True)
            ok += 1
        except Exception as e:
            fallos += 1
            if len(errores) < 10:
                errores.append(f"{Path(f).name}: {type(e).__name__}: {e}")

    print(f"cargadas sin excepción: {ok}    con excepción: {fallos}")
    for e in errores:
        print("   ", e)

    print("\nFILAS POR TABLA")
    cuentas = contar(ruta)
    for t in TABLAS:
        aviso = "   <-- VACÍA: alguna clave no se llama como el ETL espera" if not cuentas[t] else ""
        print(f"   {t:<32} {cuentas[t]:>7}{aviso}")

    # Lo importante no es que la fila exista, sino que lleve algo dentro.
    print("\nCAMPOS CON CONTENIDO")
    prods = max(1, cuentas["mapa_productos"])
    usos = max(1, cuentas["mapa_usos"])
    for k, v in rellenos(ruta).items():
        total = usos if k.startswith("mapa_usos") else prods
        print(f"   {k:<44} {v:>7}  ({100 * v / total:5.1f} %)")

    # Las fichas que no se han podido cargar son las que hay que mirar a mano.
    if fallos:
        print(f"\nATENCIÓN: {fallos} fichas no entraron. Eso es pérdida de datos, "
              "no un detalle.")
    return 1 if fallos else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 0))
