"""
descargar_catalogo.py - Traerse la base y el JSON, que ya no van en el repositorio.

Por que no estan en el repositorio
----------------------------------
La base y el JSON suman unos 120 MB y se reescriben **enteros** cada vez que
cambia algo: son binarios y git no puede guardar solo la diferencia. Medido:
~6,6 MB al dia de crecimiento, unos 2,4 GB al año, para publicar los mismos
datos una y otra vez.

Desde el 02/10/2026 se publican como **Release**, que vive fuera del
historial. El codigo sigue aqui; los datos se bajan.

    python descargar_catalogo.py

Se puede pedir una foto de una semana concreta en vez de la ultima:

    python descargar_catalogo.py --version catalogo-2026-10-04

Las fotos semanales se guardan cada domingo y sirven para responder, meses
despues, que decia el Ministerio el dia en que se firmo un recetario.
"""
import argparse
import sqlite3
import sys
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent
REPO = "fmifbar/fitosanitarios-mapa-db"
ARCHIVOS = ("fitosanitarios_mapa.db", "fitosanitarios_mapa_completo.json", "estado.json")

# Lo minimo para dar por buena una descarga. Media base es peor que ninguna:
# abre perfectamente y le faltan datos.
TABLAS = ("mapa_productos", "mapa_usos", "mapa_seguridad",
          "mapa_toxicologia", "mapa_mitigaciones")


def _url(nombre, version):
    if version in (None, "", "latest", "ultimo"):
        return f"https://github.com/{REPO}/releases/latest/download/{nombre}"
    return f"https://github.com/{REPO}/releases/download/{version}/{nombre}"


def _comprobar_base(ruta: Path) -> int:
    """Productos que trae, o -1 si lo descargado no es el catalogo."""
    try:
        con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    except Exception:
        return -1
    try:
        tablas = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if not set(TABLAS).issubset(tablas):
            return -1
        return int(con.execute("SELECT COUNT(*) FROM mapa_productos").fetchone()[0])
    except Exception:
        return -1
    finally:
        con.close()


def main(version=None, destino=None, solo=None):
    destino = Path(destino or BASE)
    destino.mkdir(parents=True, exist_ok=True)
    quiere = (solo,) if solo else ARCHIVOS

    for nombre in quiere:
        url = _url(nombre, version)
        final = destino / nombre
        # Se baja a un archivo aparte y solo se pone en su sitio al final: una
        # descarga cortada no puede sustituir a la que ya hubiera.
        parcial = final.with_suffix(final.suffix + ".descargando")
        print(f"  bajando {nombre} ...", end=" ", flush=True)
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers={"User-Agent": REPO}),
                    timeout=300) as r, open(parcial, "wb") as f:
                while True:
                    trozo = r.read(1 << 20)
                    if not trozo:
                        break
                    f.write(trozo)
        except Exception as e:
            parcial.unlink(missing_ok=True)
            print(f"FALLO: {e}")
            if nombre == "fitosanitarios_mapa.db":
                return 1
            continue

        if nombre.endswith(".db"):
            n = _comprobar_base(parcial)
            if n < 0:
                parcial.unlink(missing_ok=True)
                print("FALLO: lo descargado no es el catalogo. Se conserva lo que hubiera.")
                return 1
            print(f"{parcial.stat().st_size/1e6:.0f} MB · {n} productos")
        else:
            print(f"{parcial.stat().st_size/1e6:.0f} MB")
        parcial.replace(final)

    print("\nListo. El catalogo esta en", destino)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Descarga el catalogo desde las Releases.")
    ap.add_argument("--version", help="catalogo-AAAA-MM-DD; por defecto, el ultimo")
    ap.add_argument("--destino", help="donde dejarlo; por defecto, aqui mismo")
    ap.add_argument("--solo", help="bajar solo ese archivo")
    a = ap.parse_args()
    sys.exit(main(a.version, a.destino, a.solo))
