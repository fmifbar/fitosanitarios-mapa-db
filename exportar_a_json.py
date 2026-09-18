"""
exportar_a_json.py - Generador de archivo JSON canónico unificado
Exporta el 100% de los datos de fitosanitarios_mapa.db a un único archivo JSON jerárquico.
"""

import sys
import os
import json
import time
import sqlite3
from pathlib import Path
from catalogo_clp import traducir_ghs, traducir_h, traducir_p

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def obtener_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent

def exportar_base_de_datos_a_json(db_path: Path = None, json_salida: Path = None) -> Path:
    base_dir = obtener_base_dir()
    if db_path is None:
        db_path = base_dir / "fitosanitarios_mapa.db"
    if json_salida is None:
        json_salida = base_dir / "fitosanitarios_mapa_completo.json"

    if not db_path.exists():
        raise FileNotFoundError(f"No existe la base de datos en {db_path}")

    t0 = time.perf_counter()
    print(f"[*] Conectando a {db_path.name} para exportación canónica...")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Cargar todos los productos
    productos_rows = c.execute("""
        SELECT id, num_registro, nombre_comercial, titular, titular_direccion,
               fabricante, fabricante_direccion, estado,
               fecha_inscripcion, fecha_renovacion, fecha_caducidad, fecha_cancelacion, fecha_limite_venta,
               fabrica, otras_denominaciones, envases_autorizados,
               condiciones_generales_uso, observaciones_reglamentarias,
               tipo_formulario, sincronizado_en
        FROM mapa_productos ORDER BY id ASC
    """).fetchall()

    total_prods = len(productos_rows)
    print(f"[*] Procesando {total_prods:,} productos comerciales...")

    # Pre-cargar composiciones
    comp_map = {}
    for r in c.execute("""
        SELECT c.producto_id, s.nombre, s.nombre_ue, c.concentracion, c.unidad, s.numero_cas, s.codigo_frac_irac
        FROM mapa_producto_composicion c
        JOIN mapa_sustancias_activas s ON c.sustancia_id = s.id
    """).fetchall():
        comp_map.setdefault(r["producto_id"], []).append({
            "sustancia_activa": r["nombre"],
            "nombre_sustancia_ue": r["nombre_ue"],
            "concentracion": r["concentracion"],
            "unidad": r["unidad"],
            "numero_cas": r["numero_cas"],
            "codigo_frac_irac": r["codigo_frac_irac"]
        })

    # Pre-cargar seguridad
    seg_map = {}
    for r in c.execute("SELECT * FROM mapa_seguridad").fetchall():
        seg_map[r["producto_id"]] = {
            "seguridad_aplicador": (r["seguridad_aplicador"] or "").replace("\uf0fc", "- ").replace("\uf0a7", "- "),
            "seguridad_trabajador": (r["seguridad_trabajador"] or "").replace("\uf0fc", "- ").replace("\uf0a7", "- "),
            "plazo_reentrada": (r["plazo_reentrada"] or "").replace("\uf0fc", "- ").replace("\uf0a7", "- "),
            "frases_reduccion_riesgo": (r["frases_reduccion_riesgo"] if "frases_reduccion_riesgo" in r.keys() and r["frases_reduccion_riesgo"] else "").replace("\uf0fc", "- ").replace("\uf0a7", "- "),
            "bandas_seguridad_spe3": r["bandas_seguridad_spe3"] if "bandas_seguridad_spe3" in r.keys() else None,
            "spe8_abejas_polinizadores": r["polinizadores_spe8"] if "polinizadores_spe8" in r.keys() else None
        }

    # Pre-cargar toxicología
    tox_map = {}
    for r in c.execute("SELECT * FROM mapa_toxicologia").fetchall():
        h_list = [h.strip() for h in (r["indicaciones_h"] or "").split(",") if h.strip()]
        p_list = [p.strip() for p in (r["consejos_p"] or "").split(",") if p.strip()]
        ghs_list = [g.strip() for g in (r["pictogramas_ghs"] or "").split(",") if g.strip()]
        tox_map[r["producto_id"]] = {
            "palabra_advertencia": r["palabra_advertencia"],
            "pictogramas_ghs": [traducir_ghs(g) for g in ghs_list],
            "indicaciones_h": [traducir_h(h) for h in h_list],
            "consejos_p": [traducir_p(p) for p in p_list],
            "incompatibilidades_mezclas": r["incompatibilidades_mezclas"],
            "gestion_envases": r["gestion_envases"]
        }

    # Pre-cargar mitigaciones ambientales
    mit_map = {}
    for r in c.execute("SELECT * FROM mapa_mitigaciones").fetchall():
        mit_map.setdefault(r["producto_id"], []).append({
            "tipo_organismo": r["tipo_organismo"],
            "distancia_buffer_metros": r["distancia_buffer_metros"],
            "porcentaje_reduccion_deriva": r["porcentaje_reduccion_deriva"],
            "texto_restriccion": r["texto_restriccion"]
        })

    # Pre-cargar plazos de seguridad
    plazos_map = {}
    for r in c.execute("SELECT * FROM mapa_plazos_seguridad").fetchall():
        plazos_map.setdefault(r["producto_id"], []).append({
            "cultivo_o_grupo": r["cultivo_o_grupo"],
            "dias": r["dias"],
            "texto_declarado": r["texto_declarado"]
        })

    # Pre-cargar usos
    usos_map = {}
    for r in c.execute("""
        SELECT producto_id, cultivo_nombre, agente_nombre, codigo_cultivo, codigo_agente,
               dosis_min, dosis_max, dosis_unidad, dosis_original, num_aplicaciones_max, intervalo_min_dias,
               volumen_caldo, volumen_caldo_min, volumen_caldo_max, metodo_aplicacion, bbch,
               ambito, tipo_usuario, condiciones_especificas, plazo_seguridad_dias, plazo_seguridad_texto
        FROM mapa_usos ORDER BY id ASC
    """).fetchall():
        usos_map.setdefault(r["producto_id"], []).append({
            "cultivo": r["cultivo_nombre"],
            "codigo_cultivo": r["codigo_cultivo"],
            "plaga": r["agente_nombre"],
            "codigo_agente": r["codigo_agente"],
            "bbch": r["bbch"],
            "metodo_aplicacion": r["metodo_aplicacion"],
            "ambito_de_uso": r["ambito"],
            "tipo_usuario": r["tipo_usuario"],
            "dosis_min": r["dosis_min"],
            "dosis_max": r["dosis_max"],
            "dosis_unidad": r["dosis_unidad"],
            "dosis_original": r["dosis_original"],
            "aplicacion_max": r["num_aplicaciones_max"],
            "intervalo_min_dias": r["intervalo_min_dias"],
            "volumen_caldo": r["volumen_caldo"],
            "volumen_caldo_min": r["volumen_caldo_min"],
            "volumen_caldo_max": r["volumen_caldo_max"],
            "condiciones_especificas": r["condiciones_especificas"],
            "plazo_seguridad_dias": r["plazo_seguridad_dias"],
            "plazo_seguridad_texto": r["plazo_seguridad_texto"]
        })

    conn.close()

    # Construir JSON unificado
    catalogo_completo = []
    for p in productos_rows:
        pid = p["id"]
        prod_obj = {
            "num_registro": p["num_registro"],
            "nombre_comercial": p["nombre_comercial"],
            "titular": p["titular"],
            "titular_direccion": p["titular_direccion"],
            "fabricante": p["fabricante"],
            "fabricante_direccion": p["fabricante_direccion"],
            "fabrica": p["fabrica"],
            "otras_denominaciones": [d.strip() for d in p["otras_denominaciones"].split(",") if d.strip()] if p["otras_denominaciones"] else [],
            "envases_autorizados": p["envases_autorizados"],
            "condiciones_generales_uso": p["condiciones_generales_uso"],
            "observaciones_reglamentarias": p["observaciones_reglamentarias"],
            "estado": p["estado"],
            "fecha_inscripcion": p["fecha_inscripcion"],
            "fecha_renovacion": p["fecha_renovacion"],
            "fecha_caducidad": p["fecha_caducidad"],
            "fecha_cancelacion": p["fecha_cancelacion"],
            "fecha_limite_venta": p["fecha_limite_venta"],
            "tipo_formulario": p["tipo_formulario"],
            "sincronizado_en": p["sincronizado_en"],
            "composicion": comp_map.get(pid, []),
            "seguridad_y_epi": seg_map.get(pid, {}),
            "toxicologia_clp": tox_map.get(pid, {}),
            "mitigaciones_ambientales": mit_map.get(pid, []),
            "plazos_seguridad": plazos_map.get(pid, []),
            "usos_autorizados": usos_map.get(pid, [])
        }
        catalogo_completo.append(prod_obj)

    print(f"[*] Escribiendo archivo JSON en {json_salida.name}...")
    with open(json_salida, "w", encoding="utf-8") as f:
        json.dump(catalogo_completo, f, ensure_ascii=False, indent=2)

    t_total = time.perf_counter() - t0
    tam_mb = json_salida.stat().st_size / (1024 * 1024)
    print(f"✅ Exportación a JSON completada con éxito en {t_total:.2f} s")
    print(f"   • Archivo generado: {json_salida.name} ({tam_mb:.2f} MB)")
    print(f"   • Productos exportados: {len(catalogo_completo):,}")

    return json_salida

if __name__ == "__main__":
    exportar_base_de_datos_a_json()
