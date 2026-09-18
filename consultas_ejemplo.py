"""
consultas_ejemplo.py - Demostración de inserción y consultas agronómicas instantáneas
Simula el flujo real de prescripción técnica y validación en TT EDITOR 2.0.
"""

import sqlite3
import time
import sys
from pathlib import Path

# Asegurar codificación UTF-8 en Windows terminal
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB_FILE = Path(__file__).parent / "fitosanitarios_mapa.db"

def insertar_producto_demo():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    # 1. Insertar o recuperar Materia Activa
    cursor.execute("""
        INSERT OR IGNORE INTO mapa_sustancias_activas (nombre, numero_cas, codigo_frac_irac)
        VALUES ('BACILLUS THURINGIENSIS KURSTAKI', '68038-71-1', 'IRAC 11A');
    """)
    cursor.execute("SELECT id FROM mapa_sustancias_activas WHERE nombre = 'BACILLUS THURINGIENSIS KURSTAKI';")
    sustancia_id = cursor.fetchone()[0]

    # 2. Insertar Producto Comercial (Ejemplo: XENTARI GD / D-DIPEL)
    cursor.execute("""
        INSERT OR REPLACE INTO mapa_productos 
        (num_registro, nombre_comercial, titular, fabricante, estado, fecha_inscripcion, fecha_caducidad, tipo_formulario, clasificacion_peligrosidad)
        VALUES 
        ('19692', 'XENTARI GD', 'VALENT BIOSCIENCES', 'SUMITOMO CHEMICAL', 'Vigente', '1995-04-20', '2028-12-31', 'Granulado dispersable en agua (WG)', 'Atención / H317');
    """)
    producto_id = cursor.lastrowid or cursor.execute("SELECT id FROM mapa_productos WHERE num_registro = '19692';").fetchone()[0]

    # 3. Composición (Muchos a Muchos)
    cursor.execute("""
        INSERT OR REPLACE INTO mapa_producto_composicion (producto_id, sustancia_id, concentracion, unidad)
        VALUES (?, ?, 54.0, '% (p/p)');
    """, (producto_id, sustancia_id))

    # 4. Usos autorizados en cultivos clave (Pimiento, Tomate)
    usos_demo = [
        (producto_id, 'Pimiento', 'Orugas (Helicoverpa armigera, Spodoptera)', 0.5, 1.0, 'kg/ha', '0,5 - 1 kg/ha', 4, 7, '500-1000 l/ha', 'Aplicar al inicio de la eclosión de huevos.', 3, '3'),
        (producto_id, 'Tomate', 'Orugas (Tuta absoluta, Helicoverpa)', 0.5, 1.0, 'kg/ha', '0,5 - 1 kg/ha', 4, 7, '500-1000 l/ha', 'Tratar en las primeras fases larvarias.', 3, '3'),
        (producto_id, 'Calabacín', 'Orugas', 0.5, 0.75, 'kg/ha', '0,5 - 0,75 kg/ha', 3, 7, '400-800 l/ha', 'Uso al aire libre e invernadero.', 0, 'NO PROCEDE')
    ]
    cursor.executemany("""
        INSERT INTO mapa_usos 
        (producto_id, cultivo_nombre, agente_nombre, dosis_min, dosis_max, dosis_unidad, dosis_original, num_aplicaciones_max, intervalo_min_dias, volumen_caldo, condiciones_especificas, plazo_seguridad_dias, plazo_seguridad_texto)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, usos_demo)

    # 5. Seguridad y Toxicología
    cursor.execute("""
        INSERT OR REPLACE INTO mapa_seguridad (producto_id, seguridad_aplicador, plazo_reentrada, polinizadores_spe8)
        VALUES (?, 'Guantes de protección y mascarilla autofiltrante FFP2.', 'No entrar en el cultivo hasta que el producto esté seco.', 'Compatible con abejorros polinizadores (Bombus terrestris).');
    """, (producto_id,))

    conn.commit()
    conn.close()
    print("[+] Producto de prueba 'XENTARI GD' (Reg: 19692) insertado con éxito.")

def ejecutar_consultas_agronomicas():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    print("\n" + "=" * 70)
    print("DEMOSTRACIÓN DE CONSULTAS AGRONÓMICAS DE ALTA VELOCIDAD")
    print("=" * 70)

    # Consulta 1: Buscar productos autorizados para un cultivo y plaga con plazo <= 3 días
    cultivo = "Pimiento"
    plaga = "Orugas%"
    plazo_max = 3

    t_inicio = time.perf_counter()
    cursor.execute("""
        SELECT 
            p.nombre_comercial,
            p.num_registro,
            s.nombre AS materia_activa,
            c.concentracion || ' ' || c.unidad AS riqueza,
            u.dosis_original,
            u.dosis_min,
            u.dosis_max,
            u.dosis_unidad,
            u.plazo_seguridad_texto,
            u.condiciones_especificas
        FROM mapa_usos u
        JOIN mapa_productos p ON u.producto_id = p.id
        JOIN mapa_producto_composicion c ON p.id = c.producto_id
        JOIN mapa_sustancias_activas s ON c.sustancia_id = s.id
        WHERE u.cultivo_nombre = ?
          AND u.agente_nombre LIKE ?
          AND u.plazo_seguridad_dias <= ?
          AND p.estado = 'Vigente';
    """, (cultivo, plaga, plazo_max))
    filas = cursor.fetchall()
    t_fin = time.perf_counter()
    duracion_ms = (t_fin - t_inicio) * 1000

    print(f"\n🔍 1. Prescripción: Cultivo='{cultivo}' | Plaga='{plaga}' | Plazo Máx={plazo_max} días")
    print(f"⏱️  Tiempo de respuesta en base de datos: {duracion_ms:.3f} ms")
    for row in filas:
        print(f"   • Producto: {row[0]} (Reg: {row[1]})")
        print(f"     Materia Activa: {row[2]} ({row[3]})")
        print(f"     Dosis Legal: {row[4]} | Rango: {row[5]} a {row[6]} {row[7]}")
        print(f"     Plazo Seguridad: {row[8]} días")
        print(f"     Condiciones: {row[9]}")

    # Consulta 2: Validación automática de una receta técnica (Regla de negocio)
    print("\n🛡️ 2. Validación de Receta Técnica (Control de Dosis):")
    dosis_tecnico = 1.25  # El técnico intenta prescribir 1.25 kg/ha
    cursor.execute("""
        SELECT dosis_max, dosis_unidad, nombre_comercial 
        FROM mapa_usos u
        JOIN mapa_productos p ON u.producto_id = p.id
        WHERE p.num_registro = '19692' AND u.cultivo_nombre = 'Pimiento';
    """)
    limite = cursor.fetchone()
    if limite:
        dosis_max_permitida, unidad, prod = limite
        if dosis_tecnico > dosis_max_permitida:
            print(f"   ❌ ALERTA ROJA BLOQUEANTE: Dosis prescrita ({dosis_tecnico} {unidad}) excede el límite máximo del MAPA ({dosis_max_permitida} {unidad}) para {prod} en Pimiento.")
        else:
            print(f"   ✅ Receta validada conforme a la legalidad vigente.")

    conn.close()

if __name__ == "__main__":
    insertar_producto_demo()
    ejecutar_consultas_agronomicas()
