"""
etl_ingesta_mapa.py - Pipeline ETL de Ingesta Masiva y Delta para Fitosanitarios MAPA
Lee los PDFs oficiales, extrae su información con el Motor Canónico y la inserta
de forma relacional (3FN) con transacciones ACID en SQLite/PostgreSQL.
"""

import os
import sys
import sqlite3
import argparse
from pathlib import Path
from typing import Dict, Any, List

from motor_canonico import ExtractorFichaMAPA

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB_DEFAULT = Path(__file__).parent / "fitosanitarios_mapa.db"

def asegurar_tabla_errores(cursor: sqlite3.Cursor):
    """Crea la tabla de auditoría para registrar anomalías en fichas sin abortar el lote."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mapa_errores_ingesta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            archivo TEXT NOT NULL,
            num_registro TEXT,
            mensaje_error TEXT NOT NULL,
            fecha_error TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

def cargar_producto_en_bd(datos: Dict[str, Any], ruta_archivo: str, db_path: Path = DB_DEFAULT, forzar: bool = False) -> bool:
    """Inserta o actualiza un producto completo en una única transacción ACID."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    try:
        prod = datos["producto"]
        num_reg = prod.get("num_registro")
        if not num_reg:
            # Fallback a partir del nombre de archivo (ej: Ficha_ES-01182.pdf o Ficha_19692.pdf)
            m_fn = re.search(r'Ficha_([A-Za-z0-9\-]+)\.pdf', Path(ruta_archivo).name, re.IGNORECASE)
            if m_fn:
                num_reg = m_fn.group(1)
                prod["num_registro"] = num_reg

        if not num_reg:
            raise ValueError(f"No se pudo identificar el número de registro en {ruta_archivo}")

        # Comprobar si el producto ya existe con el mismo SHA-256 (Modo Delta)
        if not forzar:
            cursor.execute("SELECT pdf_sha256 FROM mapa_productos WHERE num_registro = ?", (num_reg,))
            row = cursor.fetchone()
            if row and row[0] == datos["sha256"]:
                # Ya está actualizado, no requiere reprocesamiento
                conn.close()
                return False

        # Iniciar transacción
        cursor.execute("BEGIN TRANSACTION;")

        # 1. Insertar o actualizar mapa_productos
        cursor.execute("""
            INSERT INTO mapa_productos (
                num_registro, nombre_comercial, titular, fabricante, estado,
                fecha_inscripcion, fecha_caducidad, tipo_formulario,
                clasificacion_peligrosidad, pdf_sha256, sincronizado_en
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(num_registro) DO UPDATE SET
                nombre_comercial = excluded.nombre_comercial,
                titular = excluded.titular,
                fabricante = excluded.fabricante,
                estado = excluded.estado,
                fecha_inscripcion = excluded.fecha_inscripcion,
                fecha_caducidad = excluded.fecha_caducidad,
                tipo_formulario = excluded.tipo_formulario,
                clasificacion_peligrosidad = excluded.clasificacion_peligrosidad,
                pdf_sha256 = excluded.pdf_sha256,
                sincronizado_en = CURRENT_TIMESTAMP;
        """, (
            num_reg,
            prod.get("nombre_comercial", ""),
            prod.get("titular", ""),
            prod.get("fabricante", ""),
            prod.get("estado", "Vigente"),
            prod.get("fecha_inscripcion"),
            prod.get("fecha_caducidad"),
            prod.get("tipo_formulario", ""),
            prod.get("clasificacion_peligrosidad", ""),
            datos["sha256"]
        ))

        cursor.execute("SELECT id FROM mapa_productos WHERE num_registro = ?", (num_reg,))
        producto_id = cursor.fetchone()[0]

        # Limpiar solo las tablas que se nutren exclusivamente de la ficha PDF
        cursor.execute("DELETE FROM mapa_seguridad WHERE producto_id = ?", (producto_id,))
        cursor.execute("DELETE FROM mapa_toxicologia WHERE producto_id = ?", (producto_id,))
        cursor.execute("DELETE FROM mapa_mitigaciones WHERE producto_id = ?", (producto_id,))

        # 2. Composición y Sustancias Activas (solo si no existía previamente)
        cursor.execute("SELECT COUNT(*) FROM mapa_producto_composicion WHERE producto_id = ?", (producto_id,))
        if cursor.fetchone()[0] == 0:
            for comp in datos.get("composicion", []):
                nombre_sust = comp["nombre"].upper().strip()
                cursor.execute("INSERT OR IGNORE INTO mapa_sustancias_activas (nombre) VALUES (?);", (nombre_sust,))
                cursor.execute("SELECT id FROM mapa_sustancias_activas WHERE nombre = ?", (nombre_sust,))
                sustancia_id = cursor.fetchone()[0]

                cursor.execute("""
                    INSERT OR REPLACE INTO mapa_producto_composicion 
                    (producto_id, sustancia_id, concentracion, unidad)
                    VALUES (?, ?, ?, ?);
                """, (producto_id, sustancia_id, comp["concentracion"], comp["unidad"]))

        # 3. Usos y Dosis
        # REGLA DE INTEGRIDAD CANÓNICA:
        # Si la base de datos ya tiene los usos limpios y estructurados del censo oficial,
        # NO los sobreescribimos con el texto segmentado del PDF. Solo insertamos si estaba vacío.
        cursor.execute("SELECT COUNT(*) FROM mapa_usos WHERE producto_id = ?", (producto_id,))
        if cursor.fetchone()[0] == 0 and datos.get("usos"):
            usos_params = []
            for u in datos.get("usos", []):
                cult = u.get("cultivo", "").strip()
                ag = u.get("agente", "").strip()
                if not cult or len(cult) < 3 or not ag or len(ag) < 3:
                    continue
                if "página" in cult.lower() or "pagina" in cult.lower():
                    continue
                usos_params.append((
                    producto_id,
                    cult,
                    ag,
                    u.get("dosis_min"),
                    u.get("dosis_max"),
                    u.get("dosis_unidad"),
                    u.get("dosis_original", ""),
                    u.get("num_aplicaciones"),
                    None,
                    u.get("volumen_caldo", ""),
                    u.get("condiciones", ""),
                    u.get("plazo_dias", 0),
                    u.get("plazo_texto", "")
                ))
            if usos_params:
                cursor.executemany("""
                    INSERT INTO mapa_usos (
                        producto_id, cultivo_nombre, agente_nombre, dosis_min, dosis_max,
                        dosis_unidad, dosis_original, num_aplicaciones_max, intervalo_min_dias,
                        volumen_caldo, condiciones_especificas, plazo_seguridad_dias, plazo_seguridad_texto
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, usos_params)

        # 4. Plazos de Seguridad (filtrando cualquier artefacto de pie de página)
        cursor.execute("DELETE FROM mapa_plazos_seguridad WHERE producto_id = ?", (producto_id,))
        plazos_params = []
        for p in datos.get("plazos_seguridad", []):
            grupo = p.get("cultivo_grupo", "").strip()
            if not grupo or len(grupo) < 3 or "página" in grupo.lower() or "pagina" in grupo.lower():
                continue
            dias = p.get("dias", 0)
            if dias > 365:
                continue
            plazos_params.append((
                producto_id,
                grupo,
                dias,
                p.get("texto", "")
            ))
        if plazos_params:
            cursor.executemany("""
                INSERT INTO mapa_plazos_seguridad (producto_id, cultivo_o_grupo, dias, texto_declarado)
                VALUES (?, ?, ?, ?);
            """, plazos_params)

        # 5. Seguridad Laboral
        seg = datos.get("seguridad", {})
        if any(seg.values()):
            cursor.execute("""
                INSERT OR REPLACE INTO mapa_seguridad (
                    producto_id, seguridad_aplicador, seguridad_trabajador, plazo_reentrada
                ) VALUES (?, ?, ?, ?);
            """, (
                producto_id,
                seg.get("seguridad_aplicador", ""),
                seg.get("seguridad_trabajador", ""),
                seg.get("plazo_reentrada", "")
            ))

        # 6. Toxicología y Clasificación CLP
        tox = datos.get("toxicologia", {})
        if any(tox.values()):
            cursor.execute("""
                INSERT OR REPLACE INTO mapa_toxicologia (
                    producto_id, palabra_advertencia, pictogramas_ghs, indicaciones_h, consejos_p,
                    incompatibilidades_mezclas, gestion_envases
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (
                producto_id,
                tox.get("palabra_advertencia", ""),
                tox.get("pictogramas_ghs", ""),
                tox.get("indicaciones_h", ""),
                tox.get("consejos_p", ""),
                tox.get("incompatibilidades_mezclas", ""),
                tox.get("gestion_envases", "")
            ))

        # 7. Mitigaciones de Riesgos Ambientales (SPe3, SPe8, SP1)
        cursor.execute("DELETE FROM mapa_mitigaciones WHERE producto_id = ?", (producto_id,))
        mits_params = []
        for m in datos.get("mitigaciones", []):
            mits_params.append((
                producto_id,
                m.get("tipo_organismo", ""),
                m.get("distancia_buffer_metros", 0),
                m.get("porcentaje_reduccion_deriva", 0),
                m.get("texto_restriccion", "")
            ))
        if mits_params:
            cursor.executemany("""
                INSERT INTO mapa_mitigaciones (
                    producto_id, tipo_organismo, distancia_buffer_metros,
                    porcentaje_reduccion_deriva, texto_restriccion
                ) VALUES (?, ?, ?, ?, ?);
            """, mits_params)

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        conn.rollback()
        asegurar_tabla_errores(cursor)
        cursor.execute("""
            INSERT INTO mapa_errores_ingesta (archivo, num_registro, mensaje_error)
            VALUES (?, ?, ?);
        """, (Path(ruta_archivo).name, datos.get("producto", {}).get("num_registro"), str(e)))
        conn.commit()
        conn.close()
        print(f"   [!] Error procesando {ruta_archivo}: {e}")
        return False

def procesar_directorio(directorio: Path, db_path: Path = DB_DEFAULT, forzar: bool = False):
    """Procesa todos los archivos PDF presentes en un directorio."""
    print(f"[*] Escaneando PDFs en: {directorio}")
    archivos_pdf = list(directorio.glob("*.pdf"))
    print(f"[*] Total de PDFs encontrados: {len(archivos_pdf)}")

    procesados = 0
    ignorados = 0
    errores = 0

    for idx, ruta in enumerate(archivos_pdf, 1):
        print(f"[{idx}/{len(archivos_pdf)}] Extrayendo: {ruta.name}...", end="", flush=True)
        try:
            extractor = ExtractorFichaMAPA(str(ruta))
            datos = extractor.procesar()
            cambiado = cargar_producto_en_bd(datos, str(ruta), db_path, forzar=forzar)
            if cambiado:
                print(f" -> OK (Reg: {datos['producto']['num_registro']} - {datos['producto']['nombre_comercial']})")
                procesados += 1
            else:
                print(" -> Sin cambios (Delta SHA-256 idéntico)")
                ignorados += 1
        except Exception as e:
            print(f" -> ERROR: {e}")
            errores += 1

    print("\n" + "=" * 60)
    print("RESUMEN DE INGESTA ETL:")
    print(f"  • Nuevos / Actualizados: {procesados}")
    print(f"  • Omitidos (sin cambios): {ignorados}")
    print(f"  • Errores / Excepciones: {errores}")
    print("=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingesta masiva relacional de fitosanitarios MAPA.")
    parser.add_argument("--dir", type=str, default=r"C:\Users\mifso\Downloads", help="Directorio con PDFs de fichas")
    parser.add_argument("--archivo", type=str, default=None, help="Ruta a un PDF específico")
    parser.add_argument("--db", type=str, default=str(DB_DEFAULT), help="Ruta al archivo de base de datos SQLite")
    parser.add_argument("--force", action="store_true", help="Forzar reingesta aunque el SHA-256 coincida")

    args = parser.parse_args()
    db_p = Path(args.db)

    if args.archivo:
        print(f"[*] Procesando archivo individual: {args.archivo}")
        extractor = ExtractorFichaMAPA(args.archivo)
        datos = extractor.procesar()
        cargar_producto_en_bd(datos, args.archivo, db_p, forzar=args.force)
        print(f"[+] Archivo ingestor completado para registro: {datos['producto']['num_registro']}")
    else:
        procesar_directorio(Path(args.dir), db_p, forzar=args.force)
