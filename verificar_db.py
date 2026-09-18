import sqlite3
import sys

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

conn = sqlite3.connect('fitosanitarios_mapa.db')
c = conn.cursor()

p = c.execute("SELECT id, num_registro, nombre_comercial, titular, estado, fecha_caducidad, pdf_sha256 FROM mapa_productos WHERE num_registro = '18926'").fetchone()
print(f"Producto ID {p[0]}: {p[1]} - {p[2]} | Titular: {p[3]} | Estado: {p[4]} | Caducidad: {p[5]}")

comp = c.execute("SELECT s.nombre, c.concentracion, c.unidad FROM mapa_producto_composicion c JOIN mapa_sustancias_activas s ON c.sustancia_id = s.id WHERE c.producto_id = ?", (p[0],)).fetchall()
print(f"Composicion ({len(comp)}): {comp}")

usos = c.execute("SELECT cultivo_nombre, agente_nombre, dosis_original, dosis_min, dosis_max, dosis_unidad, plazo_seguridad_texto, plazo_seguridad_dias FROM mapa_usos WHERE producto_id = ?", (p[0],)).fetchall()
print(f"\nUsos guardados ({len(usos)}):")
for u in usos:
    print(f"  • {u[0]} | {u[1]} | Dosis: {u[2]} (Min: {u[3]}, Max: {u[4]} {u[5]}) | P.S.: {u[6]} ({u[7]} dias)")

tox = c.execute("SELECT palabra_advertencia, pictogramas_ghs, indicaciones_h FROM mapa_toxicologia WHERE producto_id = ?", (p[0],)).fetchone()
print(f"\nToxicología: Advertencia={tox[0]} | GHS={tox[1]} | Frases H={tox[2]}")

seg = c.execute("SELECT seguridad_aplicador FROM mapa_seguridad WHERE producto_id = ?", (p[0],)).fetchone()
print(f"Seguridad aplicador: {seg[0][:90]}...")
