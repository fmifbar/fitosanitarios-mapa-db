"""
reparar_campos_borrados.py - Recuperar de una version anterior lo que se borro.

Por que existe
--------------
El 02/10/2026 la primera pasada del extractor posicional se cargo datos que ya
estaban. `cargar_producto_en_bd` usaba `INSERT OR REPLACE`, que sustituye la
fila entera, asi que donde el extractor nuevo no supo leer un campo y el motor
antiguo si lo habia leido, el campo se quedo vacio. Se perdieron 57 textos de
EPIs del aplicador, 28 de seguridad del trabajador y 15 palabras de
advertencia.

La causa ya esta arreglada (ahora es un UPSERT con COALESCE: lo nuevo gana
cuando trae algo, lo viejo se queda cuando lo nuevo viene vacio). Esto es lo
otro: devolver lo que se perdio.

Como
----
Solo rellena **campos que ahora estan vacios** con el valor que tenian antes.
No pisa nada de lo que hay ahora, asi que si el extractor nuevo mejoro un
campo, ese se queda como esta. Es la union de las dos lecturas, que es lo que
tendria que haber pasado desde el principio.

Para sacar la version anterior:
    git show <commit>:fitosanitarios_mapa.db > antes.db

Uso:
    python reparar_campos_borrados.py <antes.db> [destino.db] [--aplicar]

Sin `--aplicar` solo dice que haria. Mirar antes de tocar.
"""
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).parent

CAMPOS = {
    "mapa_seguridad": ("seguridad_aplicador", "seguridad_trabajador", "plazo_reentrada",
                       "frases_reduccion_riesgo", "bandas_seguridad_spe3",
                       "polinizadores_spe8"),
    "mapa_toxicologia": ("palabra_advertencia", "pictogramas_ghs", "indicaciones_h",
                         "consejos_p", "incompatibilidades_mezclas", "gestion_envases"),
}


def main(ruta_antes, ruta_destino=None, aplicar=False):
    antes = Path(ruta_antes)
    destino = Path(ruta_destino or BASE / "fitosanitarios_mapa.db")

    # La version vieja se abre en SOLO LECTURA: es la referencia, no se toca.
    viejo = sqlite3.connect(f"file:{antes}?mode=ro", uri=True)
    nuevo = sqlite3.connect(destino)
    try:
        viejo.row_factory = sqlite3.Row
        nuevo.row_factory = sqlite3.Row

        # Se casa por num_registro y no por producto_id: el id es interno y
        # podria no coincidir entre dos versiones de la base.
        reg_viejo = {r["num_registro"]: r["id"] for r in
                     viejo.execute("SELECT id, num_registro FROM mapa_productos")}
        reg_nuevo = {r["num_registro"]: r["id"] for r in
                     nuevo.execute("SELECT id, num_registro FROM mapa_productos")}

        total = 0
        for tabla, campos in CAMPOS.items():
            filas_viejas = {r["producto_id"]: dict(r)
                            for r in viejo.execute(f"SELECT * FROM {tabla}")}
            por_campo = {c: 0 for c in campos}

            for reg, id_n in reg_nuevo.items():
                id_v = reg_viejo.get(reg)
                if id_v is None or id_v not in filas_viejas:
                    continue
                actual = nuevo.execute(
                    f"SELECT * FROM {tabla} WHERE producto_id = ?", (id_n,)).fetchone()
                if actual is None:
                    continue
                recuperar = {}
                for c in campos:
                    ahora = (actual[c] or "").strip() if actual[c] is not None else ""
                    antes_v = filas_viejas[id_v].get(c)
                    antes_v = (antes_v or "").strip() if antes_v is not None else ""
                    if not ahora and antes_v:
                        recuperar[c] = antes_v
                        por_campo[c] += 1
                if recuperar and aplicar:
                    sets = ", ".join(f"{c} = ?" for c in recuperar)
                    nuevo.execute(f"UPDATE {tabla} SET {sets} WHERE producto_id = ?",
                                  (*recuperar.values(), id_n))

            print(f"\n{tabla}")
            for c, n in por_campo.items():
                marca = " <-" if n else ""
                print(f"   {c:<28} {n:>5} campos a recuperar{marca}")
                total += n

        if aplicar:
            nuevo.commit()
            print(f"\nAPLICADO: {total} campos recuperados.")
        else:
            print(f"\nEn seco: se recuperarian {total} campos. "
                  "Anadir --aplicar para hacerlo.")
        return total
    finally:
        viejo.close()
        nuevo.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(2)
    main(args[0], args[1] if len(args) > 1 else None, "--aplicar" in sys.argv)
