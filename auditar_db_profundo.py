import sqlite3
import json
import sys

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

conn = sqlite3.connect('fitosanitarios_mapa.db')
c = conn.cursor()

print("=== TABLAS Y CONTEO ===")
tablas = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
for t in tablas:
    count = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"• {t}: {count} filas")

print("\n=== MUESTRA DETALLADA DE FILAS EN CADA TABLA ===")
for t in tablas:
    print(f"\n--- [TABLA: {t}] ---")
    c.execute(f"PRAGMA table_info({t})")
    cols = [col[1] for col in c.fetchall()]
    print("Columnas:", cols)
    
    c.execute(f"SELECT * FROM {t} LIMIT 3")
    rows = c.fetchall()
    for idx, r in enumerate(rows, 1):
        d = dict(zip(cols, r))
        print(f"  Fila {idx}:")
        for k, v in d.items():
            val_str = str(v)
            if len(val_str) > 100:
                val_str = val_str[:100] + "..."
            print(f"    {k}: {val_str}")

# Examinar anomalías o inconsistencias
print("\n=== ANÁLISIS DE ANOMALÍAS ===")
# 1. ¿Hay duplicados o datos mal formados en mapa_usos?
c.execute("SELECT cultivo_nombre, agente_nombre, dosis_original, COUNT(*) FROM mapa_usos GROUP BY cultivo_nombre, agente_nombre, dosis_original HAVING COUNT(*) > 1 LIMIT 5")
dups = c.fetchall()
print(f"Duplicados en mapa_usos: {len(dups)}")
for d in dups:
    print(f"  {d}")

# 2. ¿Cómo están los campos de mapa_productos?
c.execute("SELECT id, num_registro, nombre_comercial, titular, estado, tipo_formulario FROM mapa_productos LIMIT 5")
print("\nMuestra mapa_productos:")
for r in c.fetchall():
    print(f"  {r}")

# 3. ¿Cómo están los usos de un producto específico (ej: Microthiol o Clementgros)?
c.execute("SELECT p.nombre_comercial, u.cultivo_nombre, u.agente_nombre, u.dosis_original, u.condiciones_especificas, u.plazo_seguridad_texto FROM mapa_usos u JOIN mapa_productos p ON u.producto_id = p.id WHERE p.num_registro = '18926' LIMIT 5")
print("\nUsos de 18926 (Clementgros):")
for r in c.fetchall():
    print(f"  {r}")
