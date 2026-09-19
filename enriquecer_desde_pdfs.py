"""
enriquecer_desde_pdfs.py - Enriquecimiento Masivo Canónico desde Fichas PDF
Procesa todos los PDFs oficiales del MAPA presentes en cache_pdfs/ e inserta/actualiza
el 100% de los datos (metadatos, plazos, usos, dosis, mitigaciones, seguridad, CLP)
de forma relacional (3FN) en fitosanitarios_mapa.db sin pérdida de información.
"""

import sys
import os
import time
from pathlib import Path
from motor_canonico import ExtractorFichaMAPA
from etl_ingesta_mapa import cargar_producto_en_bd

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def enriquecer_catalogo(db_path: Path = None, forzar: bool = False):
    base_dir = Path(__file__).parent
    if db_path is None:
        db_path = base_dir / "fitosanitarios_mapa.db"
    cache_dir = base_dir / "cache_pdfs"

    if not cache_dir.exists():
        print(f"[!] No existe el directorio {cache_dir}")
        return

    pdfs = list(cache_dir.glob("*.pdf"))
    total_pdfs = len(pdfs)
    print("======================================================================")
    print("🚀 INICIANDO ENRIQUECIMIENTO MASIVO CANÓNICO DESDE FICHAS TÉCNICAS PDF")
    print(f"[*] Total de documentos a procesar: {total_pdfs}")
    print(f"[*] Base de datos destino: {db_path.name}")
    print(f"[*] Modo forzar: {forzar}")
    print("======================================================================")

    actualizados = 0
    sin_cambios = 0
    errores = 0
    t0 = time.perf_counter()

    for idx, pdf_path in enumerate(pdfs, 1):
        try:
            extractor = ExtractorFichaMAPA(str(pdf_path))
            datos = extractor.procesar()
            
            cambiado = cargar_producto_en_bd(datos, str(pdf_path), db_path=db_path, forzar=forzar)
            if cambiado:
                actualizados += 1
            else:
                sin_cambios += 1

            if idx % 50 == 0 or idx == total_pdfs:
                t_parcial = time.perf_counter() - t0
                pct = (idx / total_pdfs) * 100
                print(f"   -> Progreso: {idx}/{total_pdfs} ({pct:.1f}%) | {actualizados} actualizados, {sin_cambios} sin cambios | {t_parcial:.1f}s transcurridos...")

        except Exception as e:
            errores += 1
            print(f"   [!] Error en {pdf_path.name}: {e}")

    t_total = time.perf_counter() - t0
    print("\n======================================================================")
    print("✅ ENRIQUECIMIENTO CANÓNICO COMPLETADO CON ÉXITO")
    print(f"  • Documentos procesados: {total_pdfs}")
    print(f"  • Productos actualizados: {actualizados}")
    print(f"  • Sin cambios (SHA-256): {sin_cambios}")
    print(f"  • Errores: {errores}")
    print(f"  • Tiempo total: {t_total:.2f} s ({t_total/max(1, actualizados):.3f} s por documento)")
    print("======================================================================")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Enriquecimiento Masivo Canónico desde PDFs")
    parser.add_argument("--force", action="store_true", help="Forzar actualización ignorando SHA-256")
    args = parser.parse_args()
    enriquecer_catalogo(forzar=args.force)
