"""
enriquecer_fichas.py - Rellena las fichas PDF que falten, poco a poco.

Qué arregla
-----------
El repositorio tenía el paso de PDF escrito (`descargador_fichas_mapa.py` y
`enriquecer_desde_pdfs.py`) pero **no corría nunca**, por dos motivos a la vez:

  1. El workflow diario solo llamaba a `sincronizar_servidor.py`.
  2. `cache_pdfs/` está en el `.gitignore` y el runner arranca limpio, así que
     aunque lo hubiera llamado habría encontrado cero PDF.

Resultado: `mapa_seguridad` (EPIs, plazo de reentrada, bandas SPe3,
polinizadores SPe8), `mapa_toxicologia` (pictogramas, frases H y P) y
`mapa_mitigaciones` estaban congeladas. Y lo peor de una tabla congelada es que
no se ve que lo está: se consulta igual y responde igual.

Cómo lo hace, y por qué así
---------------------------
**Incremental y con tope.** No se bajan las 2.080 fichas cada vez. Cada pasada
coge solo las que faltan o las que han cambiado, hasta un máximo, y espera
entre una y otra.

El servidor del Ministerio es público y lo paga todo el mundo. Bajarle 2.080
PDF cada noche para que 2.070 sean idénticos a los de ayer no es diligencia: es
ruido. Con el tope por pasada, el catálogo se completa en unas semanas y a
partir de ahí solo se tocan las que cambien.

**Qué se considera que hay que rehacer**, por este orden:
  - la que nunca se ha extraído (no tiene `pdf_sha256`),
  - aquella cuyo `estado` en el catálogo ya no es el que tenemos guardado,
  - la más antigua, si aún queda cupo.

Y si el PDF que baja resulta tener el mismo SHA-256 que el guardado, no se
reprocesa: la ficha no ha cambiado.

Uso:
    python enriquecer_fichas.py [--tope 300] [--espera 1.0] [--forzar]
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx

from adaptador_canonico import a_canonico
from descargador_fichas_mapa import URL_PDF_FICHA, obtener_catalogo_oficial_mapa
from etl_ingesta_mapa import cargar_producto_en_bd
from extractor_posicional import extraer

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).parent
DB_DEFAULT = BASE_DIR / "fitosanitarios_mapa.db"
CACHE_DIR = BASE_DIR / "cache_pdfs"

# Cuántas fichas como mucho por pasada. Con 300 a la semana, las 2.080 se
# completan en siete semanas y después solo se tocan las que cambien.
TOPE_POR_PASADA = 300

# Segundos entre descargas. No es por cortesía: es un servidor público y
# compartido, y nada de esto corre con prisa.
ESPERA_ENTRE_DESCARGAS = 1.0

# Un PDF de ficha baja de 15 kB no es una ficha: es una página de error
# devuelta con código 200, que el Ministerio hace a veces.
TAMANO_MINIMO_PDF = 15_000


def _estado_guardado(db_path: Path) -> Dict[str, Dict[str, Any]]:
    """{num_registro: {estado, sha, cuando}} de lo que ya hay en la base."""
    if not db_path.exists():
        return {}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        return {r["num_registro"]: dict(r) for r in con.execute(
            "SELECT num_registro, estado, pdf_sha256 AS sha, sincronizado_en AS cuando "
            "FROM mapa_productos")}
    finally:
        # Siempre. Es un archivo local y aquí no duele, pero es el hábito que
        # en otro servidor costó una parada.
        con.close()


def elegir(catalogo: List[Dict[str, Any]], guardado: Dict[str, Dict[str, Any]],
           tope: int, forzar: bool = False) -> List[Dict[str, Any]]:
    """
    Las fichas que toca rehacer en esta pasada, las más urgentes primero.

    Se devuelven ordenadas por prioridad y recortadas al tope, para que una
    pasada corta haga lo que más falta y no lo primero que encuentre.
    """
    if forzar:
        return catalogo[:tope]

    nunca, cambiadas, viejas = [], [], []
    for p in catalogo:
        prev = guardado.get(p["num_registro"])
        if prev is None or not prev.get("sha"):
            nunca.append(p)
        elif (p.get("estado") or "") and (p["estado"] or "") != (prev.get("estado") or ""):
            cambiadas.append(p)
        else:
            viejas.append((prev.get("cuando") or "", p))

    viejas.sort(key=lambda x: x[0])
    orden = nunca + cambiadas + [p for _, p in viejas]
    return orden[:tope]


def _bajar(client: httpx.Client, id_producto: Any, destino: Path) -> bool:
    try:
        r = client.get(f"{URL_PDF_FICHA}?idProducto={id_producto}")
    except Exception as e:
        print(f"      [!] No se pudo bajar: {e}")
        return False
    if r.status_code != 200 or r.content[:4] != b"%PDF" or len(r.content) < TAMANO_MINIMO_PDF:
        print(f"      [!] El Ministerio no devolvió una ficha (HTTP {r.status_code}, "
              f"{len(r.content)} bytes)")
        return False
    destino.write_bytes(r.content)
    return True


def enriquecer(tope: int = TOPE_POR_PASADA, espera: float = ESPERA_ENTRE_DESCARGAS,
               forzar: bool = False, db_path: Path = DB_DEFAULT) -> Dict[str, int]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    catalogo = obtener_catalogo_oficial_mapa()
    guardado = _estado_guardado(db_path)
    pendientes = elegir(catalogo, guardado, tope, forzar)

    print("=" * 70)
    print("FICHAS PDF DEL MAPA - pasada incremental")
    print(f"  catálogo oficial:        {len(catalogo)}")
    print(f"  ya extraídas:            {sum(1 for v in guardado.values() if v.get('sha'))}")
    print(f"  en esta pasada:          {len(pendientes)} (tope {tope})")
    print(f"  espera entre descargas:  {espera}s")
    print("=" * 70)

    r = {"intentadas": 0, "cargadas": 0, "sin_cambios": 0, "no_bajadas": 0, "con_error": 0}
    headers = {"User-Agent": "fitosanitarios-mapa-db (Murgiverde S.C.A.)"}

    with httpx.Client(headers=headers, timeout=60.0, follow_redirects=True, verify=False) as client:
        for i, p in enumerate(pendientes, 1):
            reg = p["num_registro"]
            r["intentadas"] += 1
            pdf = CACHE_DIR / f"Ficha_{reg}.pdf"

            if not _bajar(client, p["id_producto"], pdf):
                r["no_bajadas"] += 1
                time.sleep(espera)
                continue

            try:
                ficha = extraer(str(pdf))
                previo = (guardado.get(reg) or {}).get("sha")
                if previo and previo == ficha.get("sha256") and not forzar:
                    r["sin_cambios"] += 1
                else:
                    datos = a_canonico(ficha, num_registro_oficial=reg,
                                       id_producto_mapa=p.get("id_producto"))
                    cargar_producto_en_bd(datos, str(pdf), db_path=db_path, forzar=True)
                    r["cargadas"] += 1
            except Exception as e:
                # Una ficha mal maquetada no puede tumbar la pasada entera. Se
                # dice cuál y por qué, y se sigue con la siguiente.
                r["con_error"] += 1
                print(f"   [!] {reg}: {type(e).__name__}: {e}")
            finally:
                # El PDF no se guarda: `cache_pdfs/` está en el .gitignore y en
                # el runner no sobrevive de todas formas. Lo que queda es lo
                # extraído, que es lo que vale.
                pdf.unlink(missing_ok=True)

            if i % 25 == 0 or i == len(pendientes):
                print(f"   {i}/{len(pendientes)} · {r['cargadas']} cargadas, "
                      f"{r['sin_cambios']} sin cambios, {r['no_bajadas']} no bajadas, "
                      f"{r['con_error']} con error")
            time.sleep(espera)

    print("-" * 70)
    print(f"RESULTADO: {r}")
    quedan = sum(1 for p in catalogo
                 if not (guardado.get(p["num_registro"]) or {}).get("sha")) - r["cargadas"]
    print(f"Fichas que siguen sin extraer, aproximadamente: {max(0, quedan)}")
    print("=" * 70)
    return r


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Rellena las fichas PDF que falten, poco a poco.")
    ap.add_argument("--tope", type=int, default=TOPE_POR_PASADA,
                    help="máximo de fichas por pasada")
    ap.add_argument("--espera", type=float, default=ESPERA_ENTRE_DESCARGAS,
                    help="segundos entre descargas")
    ap.add_argument("--forzar", action="store_true",
                    help="rehacer aunque no haya cambiado")
    a = ap.parse_args()
    enriquecer(tope=a.tope, espera=a.espera, forzar=a.forzar)
