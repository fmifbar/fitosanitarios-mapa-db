"""
sincronizador_mapa.py - Sincronizador Automatizado y Programable (Cron / Task Scheduler)
Descarga y sincroniza las fichas oficiales del MAPA con control de tasa (Rate Limiting)
y detección delta (SHA-256) para mantener actualizada la base de datos sin saturar servidores.
"""

import os
import sys
import time
import argparse
import logging
from pathlib import Path
from typing import List, Optional
import httpx

from motor_canonico import ExtractorFichaMAPA
from etl_ingesta_mapa import cargar_producto_en_bd, DB_DEFAULT

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Configuración de Logging
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "sincronizacion.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

# Constantes oficiales del MAPA
MAPA_BASE_URL = "https://servicio.mapa.gob.es/regfiweb/DescargaDocumentos/Documento.aspx"
CARPETA_PDFS_CACHE = Path(__file__).parent / "cache_pdfs"
CARPETA_PDFS_CACHE.mkdir(exist_ok=True)

class SincronizadorRegistroMAPA:
    """Gestiona la descarga ordenada y sincronización periódica de productos fitosanitarios."""

    def __init__(self, db_path: Path = DB_DEFAULT, retardo_segundos: float = 0.5):
        self.db_path = db_path
        self.retardo_segundos = retardo_segundos  # Límite ético para no sobrecargar el servidor oficial (2 req/s)
        self.client = httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TT-Editor/2.0 AgriTech-Sync-Agent"
            },
            timeout=30.0,
            follow_redirects=True
        )

    def descargar_ficha_por_registro(self, num_registro: str) -> Optional[Path]:
        """Descarga el PDF oficial de un producto a partir de su número de registro."""
        params = {
            "tipoDoc": "FICHA",
            "codDoc": num_registro
        }
        url_descarga = f"{MAPA_BASE_URL}?tipoDoc=FICHA&codDoc={num_registro}"
        destino = CARPETA_PDFS_CACHE / f"Ficha_{num_registro}.pdf"

        try:
            time.sleep(self.retardo_segundos)
            resp = self.client.get(url_descarga)
            
            if resp.status_code == 200 and len(resp.content) > 1000 and resp.content[:4] == b"%PDF":
                with open(destino, "wb") as f:
                    f.write(resp.content)
                logging.info(f"Ficha descargada para registro {num_registro} ({len(resp.content)} bytes)")
                return destino
            else:
                logging.warning(f"No se pudo descargar PDF para registro {num_registro} (Status: {resp.status_code})")
                return None
        except Exception as e:
            logging.error(f"Excepción en descarga de registro {num_registro}: {e}")
            return None

    def sincronizar_lista_registros(self, lista_registros: List[str], modo_delta: bool = True):
        """Procesa una lista de números de registro."""
        logging.info(f"Iniciando sincronización de {len(lista_registros)} productos. Modo Delta: {modo_delta}")
        
        nuevos = 0
        sin_cambios = 0
        fallos = 0

        for idx, reg in enumerate(lista_registros, 1):
            reg = str(reg).strip()
            pdf_local = CARPETA_PDFS_CACHE / f"Ficha_{reg}.pdf"

            # Si no lo tenemos en caché, lo descargamos
            if not pdf_local.exists():
                pdf_local = self.descargar_ficha_por_registro(reg)
                if not pdf_local:
                    fallos += 1
                    continue

            # Procesar con el motor canónico
            try:
                extractor = ExtractorFichaMAPA(str(pdf_local))
                datos = extractor.procesar()
                actualizado = cargar_producto_en_bd(datos, str(pdf_local), self.db_path, forzar=not modo_delta)
                
                if actualizado:
                    logging.info(f"[{idx}/{len(lista_registros)}] Sincronizado: {reg} - {datos['producto']['nombre_comercial']}")
                    nuevos += 1
                else:
                    logging.info(f"[{idx}/{len(lista_registros)}] Sin cambios (SHA-256): {reg}")
                    sin_cambios += 1
            except Exception as e:
                logging.error(f"[{idx}/{len(lista_registros)}] Error en procesamiento de {reg}: {e}")
                fallos += 1

        logging.info("=" * 50)
        logging.info("FIN DE SINCRONIZACIÓN")
        logging.info(f"  • Nuevos o actualizados: {nuevos}")
        logging.info(f"  • Sin cambios: {sin_cambios}")
        logging.info(f"  • Fallos: {fallos}")
        logging.info("=" * 50)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sincronizador Periódico del Registro MAPA")
    parser.add_argument("--modo", choices=["delta", "full"], default="delta", help="Modo de sincronización")
    parser.add_argument("--registros", nargs="*", default=["18926", "19692"], help="Lista de números de registro a sincronizar")
    parser.add_argument("--db", default=str(DB_DEFAULT), help="Ruta a fitosanitarios_mapa.db")

    args = parser.parse_args()
    sinc = SincronizadorRegistroMAPA(db_path=Path(args.db))
    sinc.sincronizar_lista_registros(args.registros, modo_delta=(args.modo == "delta"))
