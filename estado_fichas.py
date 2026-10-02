"""
estado_fichas.py - Cuánto del catálogo tiene de verdad su ficha dentro.

Para qué
--------
Saber si `mapa_seguridad`, `mapa_toxicologia` y `mapa_mitigaciones` están
llenas no se responde contando filas: una fila puede existir con todos los
campos a NULL. Lo que importa es **cuántos productos tienen cada dato**.

Y de paso avisa de las anomalías que hacen que un dato parezca bueno sin
serlo, que son peores que un hueco.

Uso:
    python estado_fichas.py [ruta a la base]
"""
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).parent


def main(ruta=None):
    ruta = Path(ruta or BASE / "fitosanitarios_mapa.db")
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        uno = lambda q: con.execute(q).fetchone()[0]
        prods = uno("SELECT COUNT(*) FROM mapa_productos")
        usos = uno("SELECT COUNT(*) FROM mapa_usos")

        print("=" * 68)
        print(f"ESTADO DEL CATÁLOGO · {ruta.name} ({ruta.stat().st_size/1e6:.0f} MB)")
        print("=" * 68)
        print(f"  productos          {prods:>8}")
        print(f"  usos               {usos:>8}")
        for t in ("mapa_plazos_seguridad", "mapa_producto_composicion",
                  "mapa_sustancias_activas", "mapa_seguridad",
                  "mapa_toxicologia", "mapa_mitigaciones"):
            print(f"  {t.replace('mapa_',''):<18} {uno(f'SELECT COUNT(*) FROM {t}'):>8}")

        con_ficha = uno("SELECT COUNT(*) FROM mapa_productos "
                        "WHERE pdf_sha256 IS NOT NULL AND pdf_sha256 <> ''")
        print(f"\n  CON FICHA PDF EXTRAÍDA   {con_ficha:>6} de {prods}  "
              f"({100*con_ficha/max(1,prods):.1f} %)")

        print("\nQUÉ PRODUCTOS TIENEN CADA DATO DE LA FICHA")
        for tabla, campos in (
            ("mapa_seguridad", ("seguridad_aplicador", "seguridad_trabajador",
                                "plazo_reentrada", "bandas_seguridad_spe3",
                                "polinizadores_spe8")),
            ("mapa_toxicologia", ("palabra_advertencia", "pictogramas_ghs",
                                  "indicaciones_h", "consejos_p",
                                  "incompatibilidades_mezclas", "gestion_envases")),
        ):
            for c in campos:
                n = uno(f"SELECT COUNT(*) FROM {tabla} WHERE {c} IS NOT NULL AND {c} <> ''")
                print(f"   {c:<28} {n:>6}  ({100*n/max(1,prods):5.1f} %)")

        # ---- anomalías: datos que parecen buenos y no lo son -------------
        print("\nANOMALÍAS")
        max_cero = uno("SELECT COUNT(*) FROM mapa_usos "
                       "WHERE dosis_max = 0 AND dosis_min > 0")
        min_cero = uno("SELECT COUNT(*) FROM mapa_usos "
                       "WHERE dosis_min = 0 AND dosis_max > 0")
        # Un maximo de 0 no es «dosis cero»: es que no se supo leer la cifra.
        # Y si alguien compara «dosis <= dosis_max» para avisar de un exceso,
        # un 0 convierte cualquier dosis en un exceso. Un 0 en el minimo es
        # menos grave pero igual de falso.
        print(f"   usos con dosis_max = 0 y mínimo > 0   {max_cero:>6}  <- el máximo no se leyó")
        print(f"   usos con dosis_min = 0 y máximo > 0   {min_cero:>6}")
        sin_dosis = uno("SELECT COUNT(*) FROM mapa_usos "
                        "WHERE (dosis_min IS NULL OR dosis_min = 0) "
                        "AND (dosis_max IS NULL OR dosis_max = 0)")
        print(f"   usos sin ninguna dosis numérica       {sin_dosis:>6}")
        sin_ambito = uno("SELECT COUNT(*) FROM mapa_usos WHERE ambito IS NULL OR ambito = ''")
        print(f"   usos sin ámbito declarado             {sin_ambito:>6}")
        print("=" * 68)
    finally:
        con.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
