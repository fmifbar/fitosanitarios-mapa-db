"""
ingestar_json_mapa.py - Ingesta masiva del Registro Oficial MAPA vía endpoint nacional JSON
Descarga los 2.080 productos vigentes y sus ~35.000 usos autorizados en segundos.
"""

import sys
import os
import json
import time
import sqlite3
import httpx
import re
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def obtener_db_file() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / "fitosanitarios_mapa.db"
    return Path(__file__).parent / "fitosanitarios_mapa.db"

URL_EXPORT_JSON = "https://servicio.mapa.gob.es/regfiweb/Exportaciones/ExportJsonProductosAutorizados"

DDL_ESQUEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS mapa_productos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    num_registro TEXT NOT NULL UNIQUE,
    nombre_comercial TEXT NOT NULL,
    titular TEXT NOT NULL,
    fabricante TEXT,
    estado TEXT NOT NULL DEFAULT 'Vigente',
    fecha_inscripcion DATE,
    fecha_caducidad DATE,
    fecha_cancelacion DATE,
    fecha_limite_venta DATE,
    tipo_formulario TEXT,
    clasificacion_peligrosidad TEXT,
    pdf_url TEXT,
    pdf_sha256 TEXT,
    sincronizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mapa_sustancias_activas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    numero_cas TEXT,
    codigo_frac_irac TEXT
);

CREATE TABLE IF NOT EXISTS mapa_producto_composicion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES mapa_productos(id) ON DELETE CASCADE,
    sustancia_id INTEGER NOT NULL REFERENCES mapa_sustancias_activas(id) ON DELETE RESTRICT,
    concentracion REAL NOT NULL,
    unidad TEXT NOT NULL,
    UNIQUE(producto_id, sustancia_id)
);

CREATE TABLE IF NOT EXISTS mapa_usos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES mapa_productos(id) ON DELETE CASCADE,
    cultivo_nombre TEXT NOT NULL,
    agente_nombre TEXT NOT NULL,
    dosis_min REAL,
    dosis_max REAL,
    dosis_unidad TEXT,
    dosis_original TEXT NOT NULL,
    num_aplicaciones_max INTEGER,
    intervalo_min_dias INTEGER,
    volumen_caldo TEXT,
    ambito TEXT,
    tipo_usuario TEXT,
    condiciones_especificas TEXT,
    plazo_seguridad_dias INTEGER DEFAULT 0,
    plazo_seguridad_texto TEXT
);

CREATE TABLE IF NOT EXISTS mapa_plazos_seguridad (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES mapa_productos(id) ON DELETE CASCADE,
    cultivo_o_grupo TEXT NOT NULL,
    dias INTEGER DEFAULT 0,
    texto_declarado TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mapa_mitigaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES mapa_productos(id) ON DELETE CASCADE,
    tipo_organismo TEXT NOT NULL,
    distancia_buffer_metros INTEGER DEFAULT 0,
    porcentaje_reduccion_deriva INTEGER,
    texto_restriccion TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mapa_seguridad (
    producto_id INTEGER PRIMARY KEY REFERENCES mapa_productos(id) ON DELETE CASCADE,
    seguridad_aplicador TEXT,
    seguridad_trabajador TEXT,
    plazo_reentrada TEXT,
    bandas_seguridad_spe3 TEXT,
    polinizadores_spe8 TEXT
);

CREATE TABLE IF NOT EXISTS mapa_toxicologia (
    producto_id INTEGER PRIMARY KEY REFERENCES mapa_productos(id) ON DELETE CASCADE,
    palabra_advertencia TEXT,
    pictogramas_ghs TEXT,
    indicaciones_h TEXT,
    consejos_p TEXT,
    incompatibilidades_mezclas TEXT,
    gestion_envases TEXT
);

CREATE INDEX IF NOT EXISTS idx_mapa_prod_registro ON mapa_productos(num_registro);
CREATE INDEX IF NOT EXISTS idx_mapa_prod_estado ON mapa_productos(estado);
CREATE INDEX IF NOT EXISTS idx_mapa_usos_busqueda ON mapa_usos(cultivo_nombre, agente_nombre);
CREATE INDEX IF NOT EXISTS idx_mapa_usos_prod_cultivo ON mapa_usos(producto_id, cultivo_nombre);
CREATE INDEX IF NOT EXISTS idx_mapa_plazos_prod ON mapa_plazos_seguridad(producto_id);
"""

def descargar_e_ingestar_catalogo_nacional(db_path: Path = None, progreso_callback=None):
    if db_path is None:
        db_path = obtener_db_file()

    t_inicio = time.perf_counter()
    print("======================================================================")
    print("📡 CONECTANDO CON EL SERVIDOR OFICIAL DEL MINISTERIO DE AGRICULTURA (MAPA)")
    print("======================================================================")
    print("[*] Solicitando descarga del Catálogo Nacional Completo...")
    
    with httpx.Client(timeout=120.0, verify=False) as client:
        resp = client.post(URL_EXPORT_JSON)
        if resp.status_code != 200:
            raise RuntimeError(f"Error del servidor MAPA (Status: {resp.status_code})")
        
        t_descarga = time.perf_counter() - t_inicio
        tamano_mb = len(resp.content) / (1024 * 1024)
        print(f"[+] Archivo oficial descargado con éxito: {tamano_mb:.2f} MB en {t_descarga:.2f} segundos.")

        print("[*] Decodificando estructura de datos...")
        raw = resp.json()
        if isinstance(raw, str):
            wrapper = json.loads(raw)
        else:
            wrapper = raw
            
        if "Contenido" in wrapper:
            contenido = json.loads(wrapper["Contenido"])
        else:
            contenido = wrapper

    productos = contenido.get("Productos", [])
    total_prods = len(productos)
    print(f"[+] Total de productos comerciales oficiales detectados: {total_prods}")

    print(f"[*] Conectando a {db_path.name} para inserción relacional (3FN)...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode = WAL;")
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    # Asegurar que el esquema existe siempre
    cursor.executescript(DDL_ESQUEMA)
    for col_def in [
        ("mapa_productos", "fecha_cancelacion", "DATE"),
        ("mapa_productos", "fecha_limite_venta", "DATE"),
        ("mapa_usos", "ambito", "TEXT"),
        ("mapa_usos", "tipo_usuario", "TEXT")
    ]:
        try:
            cursor.execute(f"ALTER TABLE {col_def[0]} ADD COLUMN {col_def[1]} {col_def[2]};")
        except sqlite3.OperationalError:
            pass
    conn.commit()

    cursor.execute("PRAGMA synchronous = OFF;") # Máxima velocidad para carga masiva

    # Iniciar transacción masiva
    cursor.execute("BEGIN TRANSACTION;")

    total_usos = 0
    total_sustancias = 0

    print(f"[*] Procesando e indexando {total_prods} productos comerciales...")

    for idx, p in enumerate(productos, 1):
        dp = p.get("DATOSPRODUCTO", {})
        num_reg = str(dp.get("Num_Registro", "")).strip()
        if not num_reg:
            continue

        nombre = dp.get("Nombre", "").strip()
        titular = dp.get("Titular", "").strip()
        fabricante = dp.get("Fabricante", "").strip()
        formulado = dp.get("Formulado", "").strip()
        estado = dp.get("Estado", "Vigente").strip()
        f_inscrip = dp.get("Fecha_Registro", "").split("T")[0] if dp.get("Fecha_Registro") else None
        f_caduc = dp.get("Fecha_Caducidad", "").replace("/", "-") if dp.get("Fecha_Caducidad") else None
        f_cancel = dp.get("Fecha_Cancelacion", "").replace("/", "-").split("T")[0] if dp.get("Fecha_Cancelacion") else None
        f_lim_venta = dp.get("Fecha_LimiteVenta", "").replace("/", "-").split("T")[0] if dp.get("Fecha_LimiteVenta") else None

        # 1. Insertar producto
        cursor.execute("""
            INSERT INTO mapa_productos 
            (num_registro, nombre_comercial, titular, fabricante, estado, fecha_inscripcion, fecha_caducidad, fecha_cancelacion, fecha_limite_venta, tipo_formulario, sincronizado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(num_registro) DO UPDATE SET
                nombre_comercial = excluded.nombre_comercial,
                titular = excluded.titular,
                fabricante = excluded.fabricante,
                estado = excluded.estado,
                fecha_inscripcion = excluded.fecha_inscripcion,
                fecha_caducidad = excluded.fecha_caducidad,
                fecha_cancelacion = excluded.fecha_cancelacion,
                fecha_limite_venta = excluded.fecha_limite_venta,
                tipo_formulario = excluded.tipo_formulario,
                sincronizado_en = CURRENT_TIMESTAMP;
        """, (num_reg, nombre, titular, fabricante, estado, f_inscrip, f_caduc, f_cancel, f_lim_venta, formulado))

        cursor.execute("SELECT id FROM mapa_productos WHERE num_registro = ?", (num_reg,))
        prod_id = cursor.fetchone()[0]

        # Limpiar usos y composiciones anteriores
        cursor.execute("DELETE FROM mapa_usos WHERE producto_id = ?", (prod_id,))
        cursor.execute("DELETE FROM mapa_producto_composicion WHERE producto_id = ?", (prod_id,))

        # 2. Composición
        for c in p.get("COMPOSICION", []):
            nom_sust = c.get("Nombre Sustancia", "").strip().upper()
            if not nom_sust:
                continue
            cursor.execute("INSERT OR IGNORE INTO mapa_sustancias_activas (nombre) VALUES (?)", (nom_sust,))
            cursor.execute("SELECT id FROM mapa_sustancias_activas WHERE nombre = ?", (nom_sust,))
            sust_id = cursor.fetchone()[0]

            conc = c.get("Concentracion") or 0.0
            unidad = c.get("DescripcionNota", "%").strip()

            cursor.execute("""
                INSERT OR REPLACE INTO mapa_producto_composicion (producto_id, sustancia_id, concentracion, unidad)
                VALUES (?, ?, ?, ?);
            """, (prod_id, sust_id, conc, unidad))
            total_sustancias += 1

        # 3. Usos autorizados
        usos_lote = []
        for u in p.get("USOS", []):
            cultivo = u.get("Cultivo", "").strip()
            agente = u.get("Agente", "").strip()
            d_min = u.get("Dosis_Min")
            d_max = u.get("Dosis_Max")
            d_unidad = u.get("Unidad Medida dosis", "").strip()
            
            d_orig = f"{d_min} - {d_max} {d_unidad}" if d_min != d_max else f"{d_min} {d_unidad}"
            ps_texto = str(u.get("Plazo Seguridad", "NO PROCEDE")).strip()
            
            # Normalizar días de plazo
            ps_dias = 0
            if ps_texto.isdigit():
                ps_dias = int(ps_texto)
            elif "NO PROCEDE" not in ps_texto.upper() and "NP" not in ps_texto.upper():
                m = re.search(r'\b([0-9]+)\b', ps_texto)
                if m:
                    ps_dias = int(m.group(1))

            vol_caldo = u.get("Volumen Caldo", "").strip()
            n_aplic = None
            m_ap = str(u.get("Aplicaciones", "")).strip()
            if m_ap.isdigit():
                n_aplic = int(m_ap)
            else:
                m_nums = re.findall(r'\b([0-9]+)\b', m_ap)
                if m_nums:
                    n_aplic = int(m_nums[-1])

            interv_dias = None
            m_int = re.search(r'\b([0-9]+)\b', str(u.get("IntervaloAplicaciones", "")))
            if m_int:
                interv_dias = int(m_int.group(1))

            ambito = u.get("Ambito", "").strip()
            tipo_usuario = u.get("TipoUsuario", "").strip()
            condic = u.get("CondicionamientoEspecifico", "").strip()

            usos_lote.append((
                prod_id, cultivo, agente, d_min, d_max, d_unidad, d_orig,
                n_aplic, interv_dias, vol_caldo, ambito, tipo_usuario, condic, ps_dias, ps_texto
            ))

        if usos_lote:
            cursor.executemany("""
                INSERT INTO mapa_usos (
                    producto_id, cultivo_nombre, agente_nombre, dosis_min, dosis_max,
                    dosis_unidad, dosis_original, num_aplicaciones_max, intervalo_min_dias,
                    volumen_caldo, ambito, tipo_usuario, condiciones_especificas, plazo_seguridad_dias, plazo_seguridad_texto
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, usos_lote)
            total_usos += len(usos_lote)

        if idx % 200 == 0 or idx == total_prods:
            porcentaje = (idx / total_prods) * 100
            print(f"   -> Progreso: {idx}/{total_prods} productos cargados ({porcentaje:.1f}%) | {total_usos} usos indexados...")

    conn.commit()
    cursor.execute("PRAGMA synchronous = NORMAL;")
    conn.close()

    t_total = time.perf_counter() - t_inicio
    print("\n" + "=" * 70)
    print("✅ CARGA MASIVA NACIONAL COMPLETADA CON ÉXITO")
    print(f"  • Productos Registrados: {total_prods}")
    print(f"  • Usos Agronómicos Indexados: {total_usos}")
    print(f"  • Materias Activas Normalizadas: {total_sustancias}")
    print(f"  • Tiempo Total de Ejecución: {t_total:.2f} segundos")
    print("======================================================================")

if __name__ == "__main__":
    descargar_e_ingestar_catalogo_nacional()
