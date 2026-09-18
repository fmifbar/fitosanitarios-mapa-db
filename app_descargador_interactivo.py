"""
app_descargador_interactivo.py - Aplicación Interactiva Ejecutable (.exe)
TT EDITOR 2.0 - Sistema Autónomo de Descarga e Ingesta del Registro Oficial MAPA
Descarga y extrae el 100% de los datos de las fichas originales en PDF del Ministerio de Agricultura.
"""

import sys
import os
import time
import sqlite3
from pathlib import Path

# Asegurar codificación UTF-8 en consola de Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def obtener_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent

BASE_DIR = obtener_base_dir()
DB_FILE = BASE_DIR / "fitosanitarios_mapa.db"
CACHE_DIR = BASE_DIR / "cache_pdfs"
CACHE_DIR.mkdir(exist_ok=True)

from ingestar_json_mapa import descargar_e_ingestar_catalogo_nacional
from descargador_fichas_mapa import sincronizar_fichas_completas, descargar_y_procesar_producto, obtener_catalogo_oficial_mapa
from etl_ingesta_mapa import procesar_directorio
from exportar_a_json import exportar_base_de_datos_a_json
import httpx

def limpiar_pantalla():
    os.system("cls" if os.name == "nt" else "clear")

def mostrar_banner():
    print(r"""
===============================================================================
       🌾 TT EDITOR 2.0 - DESCARGADOR OFICIAL DE FITOSANITARIOS MAPA 🌾
       Extracción Canónica de FICHAS ORIGINALES EN PDF y Base de Datos 3FN
===============================================================================
    """)

def ver_estadisticas():
    limpiar_pantalla()
    mostrar_banner()
    print("📊 ESTADÍSTICAS ACTUALES DE LA BASE DE DATOS LOCAL\n")

    if not DB_FILE.exists():
        print("⚠️  La base de datos aún no ha sido creada. Seleccione la Opción 1 o 2 para inicializarla.")
        input("\nPresione ENTER para volver al menú...")
        return

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    total_prod = c.execute("SELECT COUNT(*) FROM mapa_productos").fetchone()[0]
    total_vigentes = c.execute("SELECT COUNT(*) FROM mapa_productos WHERE estado = 'Vigente'").fetchone()[0]
    total_usos = c.execute("SELECT COUNT(*) FROM mapa_usos").fetchone()[0]
    total_bbch = c.execute("SELECT COUNT(*) FROM mapa_usos WHERE bbch IS NOT NULL AND bbch != ''").fetchone()[0]
    total_siex = c.execute("SELECT COUNT(*) FROM mapa_usos WHERE codigo_cultivo IS NOT NULL AND codigo_cultivo != ''").fetchone()[0]
    total_sust = c.execute("SELECT COUNT(*) FROM mapa_sustancias_activas").fetchone()[0]
    total_seg = c.execute("SELECT COUNT(*) FROM mapa_seguridad").fetchone()[0]
    total_tox = c.execute("SELECT COUNT(*) FROM mapa_toxicologia").fetchone()[0]
    total_mit = c.execute("SELECT COUNT(*) FROM mapa_mitigaciones").fetchone()[0]
    total_plazos = c.execute("SELECT COUNT(*) FROM mapa_plazos_seguridad").fetchone()[0]
    tamano_mb = DB_FILE.stat().st_size / (1024 * 1024)

    print(f"  • Archivo Base de Datos: {DB_FILE.name} ({tamano_mb:.2f} MB)")
    print(f"  • 1. Productos Registrados:        {total_prod:,}")
    print(f"  • 2. Materias Activas Normalizadas: {total_sust:,}")
    print(f"  • 3. Usos Agronómicos Indexados:   {total_usos:,}")
    print(f"  • 4. Códigos SIEX Oficiales:       {total_siex:,}")
    print(f"  • 5. Estadios BBCH / Cuaderno CUE: {total_bbch:,}")
    print(f"  • 6. Plazos de Seguridad:          {total_plazos:,}")
    print(f"  • 7. Fichas con Seguridad (EPIs):  {total_seg:,}")
    print(f"  • 8. Fichas con Toxicología (CLP): {total_tox:,}")
    print(f"  • 9. Mitigaciones Ambientales:     {total_mit:,}")
    
    ultimos = c.execute("SELECT nombre_comercial, num_registro, titular FROM mapa_productos ORDER BY id DESC LIMIT 3").fetchall()
    if ultimos:
        print("\n  Últimos registros en la base de datos:")
        for u in ultimos:
            print(f"    - {u[0]} (Reg: {u[1]}) | {u[2]}")

    conn.close()
    input("\nPresione ENTER para volver al menú principal...")

def buscar_interactivo():
    limpiar_pantalla()
    mostrar_banner()
    print("🔍 BUSCADOR INTEGRAL DE FITOSANITARIOS, USOS Y SEGURIDAD")
    termino = input("\nIngrese cultivo, plaga, producto o materia activa (ej: 'Tomate', 'Pimiento', 'Trips', 'Xentari'): ").strip()
    if not termino:
        return

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    patron = f"%{termino}%"

    t0 = time.perf_counter()
    c.execute("""
        SELECT 
            p.nombre_comercial,
            p.num_registro,
            u.cultivo_nombre,
            u.agente_nombre,
            u.dosis_original,
            u.plazo_seguridad_texto,
            COALESCE(s.seguridad_aplicador, 'Ver ficha técnica') AS seguridad,
            COALESCE(t.palabra_advertencia, '-') AS adv,
            COALESCE(t.pictogramas_ghs, '-') AS ghs
        FROM mapa_usos u
        JOIN mapa_productos p ON u.producto_id = p.id
        LEFT JOIN mapa_seguridad s ON p.id = s.producto_id
        LEFT JOIN mapa_toxicologia t ON p.id = t.producto_id
        WHERE u.cultivo_nombre LIKE ? 
           OR u.agente_nombre LIKE ?
           OR p.nombre_comercial LIKE ?
        LIMIT 10;
    """, (patron, patron, patron))
    filas = c.fetchall()
    ms = (time.perf_counter() - t0) * 1000

    print(f"\n[+] Resultados para '{termino}' ({len(filas)} encontrados en {ms:.2f} ms):\n")
    for r in filas:
        print(f"  • {r[0]} (Reg: {r[1]})")
        print(f"    Cultivo: {r[2]} | Plaga: {r[3]}")
        print(f"    Dosis: {r[4]} | Plazo Seguridad: {r[5]}")
        print(f"    Toxicología: {r[7]} (Pictogramas: {r[8]})")
        print(f"    Seguridad Aplicador: {r[6][:90]}...")
        print("  " + "-" * 70)

    conn.close()
    input("\nPresione ENTER para volver al menú...")

def menu_descarga_fichas_pdf():
    limpiar_pantalla()
    mostrar_banner()
    print("📥 DESCARGA Y EXTRACCIÓN DE FICHAS ORIGINALES EN PDF (MAPA)\n")
    print("Seleccione el alcance de descarga:")
    print("  [1] 🍅 Cultivos Prioritarios (Tomate, Pimiento, Pepino, Calabacín, Melón, Sandía, Cítricos)")
    print("  [2] 🧪 Lote de Prueba Rápido (10 fichas oficiales)")
    print("  [3] 📦 Catálogo Nacional Completo (~2.080 fichas PDF)")
    print("  [4] 🎯 Un producto específico por Número de Registro")
    print("  [5] 🔙 Volver")

    opc = input("\nSeleccione opción [1-5]: ").strip()
    if opc == "1":
        cultivo = input("Escriba cultivo (Enter para 'Tomate'): ").strip() or "Tomate"
        sincronizar_fichas_completas(filtro_cultivo=cultivo, db_path=DB_FILE)
    elif opc == "2":
        sincronizar_fichas_completas(limite=10, db_path=DB_FILE)
    elif opc == "3":
        confirmar = input("¿Desea descargar las ~2.080 fichas oficiales completas? [s/n]: ").strip().lower()
        if confirmar == "s":
            sincronizar_fichas_completas(limite=None, db_path=DB_FILE)
    elif opc == "4":
        reg_buscado = input("Número de registro a descargar (ej: '18926', '19692'): ").strip()
        if reg_buscado:
            catalogo = obtener_catalogo_oficial_mapa()
            coincidentes = [p for p in catalogo if p["num_registro"] == reg_buscado]
            if coincidentes:
                client = httpx.Client(timeout=30, verify=False)
                descargar_y_procesar_producto(coincidentes[0], client, db_path=DB_FILE, forzar=True)
                client.close()
                print(f"\n✅ Ficha {reg_buscado} ({coincidentes[0]['nombre_comercial']}) descargada y procesada al 100%.")
            else:
                print(f"⚠️  No se encontró el registro {reg_buscado} en el catálogo oficial.")
    input("\nPresione ENTER para continuar...")

def iniciar_servidor_api():
    limpiar_pantalla()
    mostrar_banner()
    print("🚀 INICIANDO SERVIDOR API REST DE TT EDITOR 2.0 (FastAPI)...")
    print("   Dirección local: http://localhost:8000")
    print("   Documentación interactiva Swagger: http://localhost:8000/docs")
    print("\n   Presione Ctrl + C para detener el servidor y volver al menú.\n")
    import uvicorn
    from api_fitosanitarios import app
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
    except KeyboardInterrupt:
        print("\nServidor detenido.")
        time.sleep(1)

def menu_principal():
    while True:
        limpiar_pantalla()
        mostrar_banner()
        print("Seleccione una opción:\n")
        print("  [1] 📄 Descargar FICHAS PDF Originales y Extraer Seguridad, Dosis y Mitigaciones (100%)")
        print("  [2] ⚡ Sincronización Rápida Nacional (Usos y Dosis Oficiales vía JSON en 5s)")
        print("  [3] 🔍 Buscar Fitosanitario, Plaga, Dosis o EPIs en la Base de Datos")
        print("  [4] 📊 Ver Estadísticas de la Base de Datos (8 Tablas Relacionales)")
        print("  [5] 🚀 Iniciar Servidor API (FastAPI) para TT EDITOR 2.0")
        print("  [6] 📁 Procesar Carpeta con Fichas PDF Locales")
        print("  [7] 📦 Exportar Toda la Base de Datos a JSON Unificado (.json)")
        print("  [8] ❌ Salir")

        opcion = input("\nOpción seleccionada [1-8]: ").strip()

        if opcion == "1":
            menu_descarga_fichas_pdf()
        elif opcion == "2":
            limpiar_pantalla()
            mostrar_banner()
            descargar_e_ingestar_catalogo_nacional(db_path=DB_FILE)
            input("\nPresione ENTER para continuar...")
        elif opcion == "3":
            buscar_interactivo()
        elif opcion == "4":
            ver_estadisticas()
        elif opcion == "5":
            iniciar_servidor_api()
        elif opcion == "6":
            ruta_dir = input("\nIngrese la ruta de la carpeta con PDFs (Enter para 'Downloads'): ").strip()
            if not ruta_dir:
                ruta_dir = str(Path.home() / "Downloads")
            procesar_directorio(Path(ruta_dir), db_path=DB_FILE)
            input("\nPresione ENTER para volver...")
        elif opcion == "7":
            limpiar_pantalla()
            mostrar_banner()
            print("📦 EXPORTANDO BASE DE DATOS COMPLETA A FORMATO JSON...\n")
            json_generado = exportar_base_de_datos_a_json(db_path=DB_FILE)
            print(f"\n[+] Ubicación: {json_generado.resolve()}")
            input("\nPresione ENTER para volver al menú...")
        elif opcion == "8":
            print("\n¡Hasta pronto!")
            time.sleep(1)
            break
        else:
            print("\nOpción no válida. Intente de nuevo.")
            time.sleep(1)

if __name__ == "__main__":
    menu_principal()
