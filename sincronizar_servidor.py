"""
sincronizar_servidor.py - Sincronización automática desatendida para GitHub Actions y Servidores
1. Descarga el catálogo nacional oficial MAPA más reciente.
2. Actualiza los 2.080 productos y ~62.000 usos en fitosanitarios_mapa.db.
3. Exporta la base completa a fitosanitarios_mapa_completo.json.
4. Genera un informe de estado con estadísticas.
"""

import sys
import os
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
DB_FILE = BASE_DIR / "fitosanitarios_mapa.db"
JSON_FILE = BASE_DIR / "fitosanitarios_mapa_completo.json"

from ingestar_json_mapa import descargar_e_ingestar_catalogo_nacional
from exportar_a_json import exportar_base_de_datos_a_json
import sqlite3

def main():
    print("======================================================================")
    print("🌾 TT EDITOR 2.0 - SINCRONIZADOR AUTOMÁTICO EN LA NUBE (MAPA)")
    print("======================================================================")
    
    # 1. Sincronizar catálogo nacional
    print("\n[1/4] Descargando y sincronizando catálogo nacional del MAPA...")
    descargar_e_ingestar_catalogo_nacional(db_path=DB_FILE)
    
    # 2. Enriquecer con fichas PDF oficiales (si existen en caché)
    cache_dir = BASE_DIR / "cache_pdfs"
    if cache_dir.exists() and any(cache_dir.glob("*.pdf")):
        print("\n[2/4] Enriqueciendo datos con máxima fidelidad desde fichas técnicas PDF...")
        from enriquecer_desde_pdfs import enriquecer_catalogo
        enriquecer_catalogo(db_path=DB_FILE, forzar=False)
    else:
        print("\n[2/4] No se detectó directorio cache_pdfs/ con archivos PDF.")

    # 3. Exportar a JSON unificado
    print("\n[3/4] Generando archivo JSON canónico de alta disponibilidad...")
    exportar_base_de_datos_a_json(db_path=DB_FILE, json_salida=JSON_FILE)
    
    # 4. Resumen estadístico
    print("\n[4/4] Verificando métricas de integridad:")
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    tablas = [
        'mapa_productos',
        'mapa_sustancias_activas',
        'mapa_producto_composicion',
        'mapa_usos',
        'mapa_plazos_seguridad',
        'mapa_seguridad',
        'mapa_toxicologia',
        'mapa_mitigaciones'
    ]
    for t in tablas:
        cant = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"   • {t:<26}: {cant:,}")
    conn.close()
    
    print("\n✅ PROCESO COMPLETADO SATISFACTORIAMENTE.")

if __name__ == "__main__":
    main()
