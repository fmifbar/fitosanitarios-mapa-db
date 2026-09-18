"""
enriquecer_desde_pdfs.py - Enriquecimiento Masivo de Fitosanitarios desde Fichas PDF
Extrae envases autorizados, fecha de renovación, sedes postales, directrices agronómicas,
instrucciones del aplicador y normativas regulatorias desde todos los PDFs en cache_pdfs.
"""

import sys
import os
import time
import sqlite3
import re
from pathlib import Path
from motor_canonico import ExtractorFichaMAPA

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def enriquecer_catalogo():
    base_dir = Path(__file__).parent
    db_path = base_dir / "fitosanitarios_mapa.db"
    cache_dir = base_dir / "cache_pdfs"

    if not cache_dir.exists():
        print(f"[!] No existe el directorio {cache_dir}")
        return

    pdfs = list(cache_dir.glob("*.pdf"))
    total_pdfs = len(pdfs)
    print("======================================================================")
    print("🚀 INICIANDO ENRIQUECIMIENTO MASIVO DESDE FICHAS TÉCNICAS EN PDF")
    print(f"[*] Total de documentos a procesar: {total_pdfs}")
    print("======================================================================")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode = WAL;")
    cursor.execute("PRAGMA synchronous = NORMAL;")

    actualizados = 0
    errores = 0
    t0 = time.perf_counter()

    for idx, pdf_path in enumerate(pdfs, 1):
        try:
            extractor = ExtractorFichaMAPA(str(pdf_path))
            datos = extractor.procesar()
            prod = datos.get("producto", {})
            seg = datos.get("seguridad", {})
            tox = datos.get("toxicologia", {})

            num_reg = prod.get("num_registro")
            if not num_reg:
                m_fn = re.search(r'Ficha_([A-Za-z0-9\-]+)\.pdf', pdf_path.name, re.IGNORECASE)
                if m_fn:
                    num_reg = m_fn.group(1).strip()

            if not num_reg:
                continue

            # Buscar ID del producto
            cursor.execute("SELECT id FROM mapa_productos WHERE num_registro = ?", (num_reg,))
            row = cursor.fetchone()
            if not row:
                continue
            pid = row[0]

            # 1. Actualizar campos administrativos y regulatorios del producto
            cursor.execute("""
                UPDATE mapa_productos SET
                    fecha_renovacion = COALESCE(?, fecha_renovacion),
                    titular_direccion = COALESCE(?, titular_direccion),
                    fabricante_direccion = COALESCE(?, fabricante_direccion),
                    envases_autorizados = COALESCE(?, envases_autorizados),
                    condiciones_generales_uso = COALESCE(?, condiciones_generales_uso),
                    observaciones_reglamentarias = COALESCE(?, observaciones_reglamentarias),
                    pdf_sha256 = ?
                WHERE id = ?;
            """, (
                prod.get("fecha_renovacion"),
                prod.get("titular_direccion") or None,
                prod.get("fabricante_direccion") or None,
                prod.get("envases_autorizados") or None,
                prod.get("condiciones_generales_uso") or None,
                prod.get("observaciones_reglamentarias") or None,
                datos.get("sha256"),
                pid
            ))

            # 2. Actualizar seguridad laboral y EPIs
            if any(seg.values()):
                cursor.execute("""
                    INSERT INTO mapa_seguridad (
                        producto_id, seguridad_aplicador, seguridad_trabajador, plazo_reentrada,
                        frases_reduccion_riesgo, bandas_seguridad_spe3, polinizadores_spe8
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(producto_id) DO UPDATE SET
                        seguridad_aplicador = CASE WHEN excluded.seguridad_aplicador != '' THEN excluded.seguridad_aplicador ELSE mapa_seguridad.seguridad_aplicador END,
                        seguridad_trabajador = CASE WHEN excluded.seguridad_trabajador != '' THEN excluded.seguridad_trabajador ELSE mapa_seguridad.seguridad_trabajador END,
                        plazo_reentrada = CASE WHEN excluded.plazo_reentrada != '' THEN excluded.plazo_reentrada ELSE mapa_seguridad.plazo_reentrada END,
                        frases_reduccion_riesgo = CASE WHEN excluded.frases_reduccion_riesgo != '' THEN excluded.frases_reduccion_riesgo ELSE mapa_seguridad.frases_reduccion_riesgo END,
                        bandas_seguridad_spe3 = COALESCE(excluded.bandas_seguridad_spe3, mapa_seguridad.bandas_seguridad_spe3),
                        polinizadores_spe8 = COALESCE(excluded.polinizadores_spe8, mapa_seguridad.polinizadores_spe8);
                """, (
                    pid,
                    seg.get("seguridad_aplicador", ""),
                    seg.get("seguridad_trabajador", ""),
                    seg.get("plazo_reentrada", ""),
                    seg.get("frases_reduccion_riesgo", ""),
                    seg.get("bandas_seguridad_spe3") or None,
                    seg.get("polinizadores_spe8") or None
                ))

            # 3. Actualizar toxicología CLP si existe
            if any(tox.values()):
                cursor.execute("""
                    INSERT INTO mapa_toxicologia (
                        producto_id, palabra_advertencia, pictogramas_ghs, indicaciones_h, consejos_p,
                        incompatibilidades_mezclas, gestion_envases
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(producto_id) DO UPDATE SET
                        palabra_advertencia = CASE WHEN excluded.palabra_advertencia != '' THEN excluded.palabra_advertencia ELSE mapa_toxicologia.palabra_advertencia END,
                        pictogramas_ghs = CASE WHEN excluded.pictogramas_ghs != '' THEN excluded.pictogramas_ghs ELSE mapa_toxicologia.pictogramas_ghs END,
                        indicaciones_h = CASE WHEN excluded.indicaciones_h != '' THEN excluded.indicaciones_h ELSE mapa_toxicologia.indicaciones_h END,
                        consejos_p = CASE WHEN excluded.consejos_p != '' THEN excluded.consejos_p ELSE mapa_toxicologia.consejos_p END,
                        incompatibilidades_mezclas = CASE WHEN excluded.incompatibilidades_mezclas != '' THEN excluded.incompatibilidades_mezclas ELSE mapa_toxicologia.incompatibilidades_mezclas END,
                        gestion_envases = CASE WHEN excluded.gestion_envases != '' THEN excluded.gestion_envases ELSE mapa_toxicologia.gestion_envases END;
                """, (
                    pid,
                    tox.get("palabra_advertencia", ""),
                    tox.get("pictogramas_ghs", ""),
                    tox.get("indicaciones_h", ""),
                    tox.get("consejos_p", ""),
                    tox.get("incompatibilidades_mezclas", ""),
                    tox.get("gestion_envases", "")
                ))

            actualizados += 1

            if idx % 100 == 0 or idx == total_pdfs:
                conn.commit()
                t_parcial = time.perf_counter() - t0
                pct = (idx / total_pdfs) * 100
                print(f"   -> Progreso: {idx}/{total_pdfs} ({pct:.1f}%) | {t_parcial:.1f}s transcurridos...")

        except Exception as e:
            errores += 1
            print(f"   [!] Error en {pdf_path.name}: {e}")

    conn.commit()
    conn.close()

    t_total = time.perf_counter() - t0
    print("\n======================================================================")
    print("✅ ENRIQUECIMIENTO COMPLETADO CON ÉXITO")
    print(f"  • Documentos procesados: {actualizados}")
    print(f"  • Errores: {errores}")
    print(f"  • Tiempo total: {t_total:.2f} s ({t_total/max(1, actualizados):.3f} s por documento)")
    print("======================================================================")

if __name__ == "__main__":
    enriquecer_catalogo()
