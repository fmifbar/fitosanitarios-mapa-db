"""
comparar_dias_del_catalogo.py - ¿De verdad hace falta sincronizar a diario?

La pregunta
-----------
La web del Registro dice que el Ministerio actualiza **una vez por semana, los
viernes a partir de las 14:00**. Si es asi, seis de cada siete ejecuciones
diarias se bajan exactamente lo mismo y no aportan nada.

Pero el archivo del repositorio cambia los siete dias, porque se regenera
entero con sus propias marcas de tiempo. Eso no demuestra que el catalogo
haya cambiado: solo que el archivo es otro.

Lo que si lo demuestra
----------------------
Comparar **el contenido que importa** —el estado de cada producto— entre
fotos de dias distintos. Se compara la huella del conjunto
`(num_registro, estado)`, que ignora las marcas de tiempo.

Y se hace con control: una foto **anterior** a la publicacion del viernes y
varias **posteriores**. Si la teoria vale, las posteriores seran identicas
entre si y distintas de la anterior.

Uso:
    python comparar_dias_del_catalogo.py <sha>:<etiqueta> <sha>:<etiqueta> ...
"""
import hashlib
import sqlite3
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = "fmifbar/fitosanitarios-mapa-db"


def huella_de(sha: str) -> tuple:
    """(huella de los estados, productos, vigentes) de esa foto del catalogo."""
    url = f"https://raw.githubusercontent.com/{REPO}/{sha}/fitosanitarios_mapa.db"
    tmp = Path(tempfile.gettempdir()) / f"foto_{sha[:8]}.db"
    with urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": REPO}), timeout=300) as r, \
            open(tmp, "wb") as f:
        while True:
            t = r.read(1 << 20)
            if not t:
                break
            f.write(t)
    try:
        con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        try:
            filas = con.execute(
                "SELECT num_registro, estado, fecha_caducidad FROM mapa_productos "
                "ORDER BY num_registro").fetchall()
            vig = sum(1 for _, e, _c in filas if (e or "").strip().lower() == "vigente")
            # Tambien los usos: lo que de verdad se receta son la dosis, el
            # plazo y el cultivo, no solo el estado del producto. Un catalogo
            # puede no dar de baja a nadie y haber cambiado una dosis.
            usos = con.execute(
                "SELECT p.num_registro, u.cultivo_nombre, u.agente_nombre, "
                "       u.dosis_original, u.plazo_seguridad_texto "
                "FROM mapa_usos u JOIN mapa_productos p ON p.id = u.producto_id "
                "ORDER BY p.num_registro, u.cultivo_nombre, u.agente_nombre").fetchall()
        finally:
            con.close()
    finally:
        for s in ("", "-wal", "-shm"):
            Path(str(tmp) + s).unlink(missing_ok=True)

    h_est = hashlib.sha256(
        "\n".join(f"{r}\t{e}\t{c}" for r, e, c in filas).encode("utf-8")).hexdigest()
    h_usos = hashlib.sha256(
        "\n".join("\t".join(str(x) for x in u) for u in usos).encode("utf-8")).hexdigest()
    return (h_est, h_usos), len(filas), vig, len(usos)


def main(args):
    resultados = []
    for a in args:
        sha, _, etiqueta = a.partition(":")
        print(f"  bajando {etiqueta or sha[:8]} ...", end=" ", flush=True)
        h, n, v, nu = huella_de(sha)
        print(f"{n} productos, {v} vigentes, {nu} usos")
        resultados.append((etiqueta or sha[:8], h, n, v, nu))

    print(f"\n{'':<28}{'estados':<20}{'usos (dosis y plazos)':<22}")
    for etiqueta, (he, hu), n, v, nu in resultados:
        print(f"   {etiqueta:<25}{he[:16]:<20}{hu[:16]:<22}")

    print("\nCOMPARACION CON", resultados[0][0])
    base = resultados[0][1]
    for etiqueta, h, n, v, nu in resultados[1:]:
        est = "iguales " if h[0] == base[0] else "DISTINTOS"
        uso = "iguales " if h[1] == base[1] else "DISTINTOS"
        print(f"   {etiqueta:<28} estados: {est}   usos: {uso}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
