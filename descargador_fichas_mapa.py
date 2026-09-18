"""
descargador_fichas_mapa.py - Descarga masiva y extracción canónica de PDFs oficiales MAPA
Descarga las FICHAS técnicas oficiales originales en PDF (A3 Landscape) e indexa el 100%
de los datos: seguridad del aplicador, reentrada, mitigaciones SPe3, toxicología CLP y usos.
"""

import sys
import os
import time
import json
import sqlite3
import httpx
from pathlib import Path
from typing import List, Dict, Any, Optional

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
DB_DEFAULT = BASE_DIR / "fitosanitarios_mapa.db"
CACHE_DIR = BASE_DIR / "cache_pdfs"
CACHE_DIR.mkdir(exist_ok=True)

URL_JSON_CATALOGO = "https://servicio.mapa.gob.es/regfiweb/Exportaciones/ExportJsonProductosAutorizados"
URL_PDF_FICHA = "https://servicio.mapa.gob.es/regfiweb/Productos/ExportFichaProductoPdfGet"

from motor_canonico import ExtractorFichaMAPA
from etl_ingesta_mapa import cargar_producto_en_bd

def obtener_catalogo_oficial_mapa() -> List[Dict[str, Any]]:
    """Descarga el catálogo nacional para obtener el IdProducto y Num_Registro de todas las fichas."""
    print("[*] Obteniendo censo oficial de productos desde el Ministerio de Agricultura...")
    with httpx.Client(timeout=60.0, verify=False) as client:
        resp = client.post(URL_JSON_CATALOGO)
        if resp.status_code != 200:
            raise RuntimeError(f"Error al contactar con el MAPA (Status: {resp.status_code})")
        
        raw = resp.json()
        wrapper = json.loads(raw) if isinstance(raw, str) else raw
        contenido = json.loads(wrapper["Contenido"]) if "Contenido" in wrapper else wrapper

    productos_raw = contenido.get("Productos", [])
    catalogo = []
    for p in productos_raw:
        dp = p.get("DATOSPRODUCTO", {})
        id_prod = dp.get("IdProducto")
        num_reg = str(dp.get("Num_Registro", "")).strip()
        nombre = dp.get("Nombre", "").strip()
        cultivos = [u.get("Cultivo", "").strip() for u in p.get("USOS", [])]
        if id_prod and num_reg:
            catalogo.append({
                "id_producto": id_prod,
                "num_registro": num_reg,
                "nombre_comercial": nombre,
                "cultivos": cultivos
            })
    return catalogo

def descargar_y_procesar_producto(prod_info: Dict[str, Any], client: httpx.Client, db_path: Path = DB_DEFAULT, forzar: bool = False) -> bool:
    """Descarga el PDF original de una ficha, lo procesa con el motor canónico y lo inserta en 3FN."""
    num_reg = prod_info["num_registro"]
    id_prod = prod_info["id_producto"]
    nombre = prod_info["nombre_comercial"]
    pdf_destino = CACHE_DIR / f"Ficha_{num_reg}.pdf"

    # Si ya existe en caché local y no forzamos re-descarga, saltar la petición HTTP
    if not pdf_destino.exists() or forzar:
        try:
            url = f"{URL_PDF_FICHA}?idProducto={id_prod}"
            r = client.get(url)
            if r.status_code == 200 and len(r.content) > 1000 and r.content[:4] == b"%PDF":
                with open(pdf_destino, "wb") as f:
                    f.write(r.content)
            else:
                return False
        except Exception:
            return False

    # Extraer todo el contenido del PDF con el motor canónico
    try:
        extractor = ExtractorFichaMAPA(str(pdf_destino))
        datos = extractor.procesar()
        
        # Enriquecer datos con IdProducto oficial si no estaba
        datos["producto"]["id_producto_mapa"] = id_prod
        
        # Cargar de forma relacional en la base de datos
        cargar_producto_en_bd(datos, str(pdf_destino), db_path=db_path, forzar=True)
        return True
    except Exception as e:
        print(f"      [!] Error interpretando PDF de {num_reg} ({nombre}): {e}")
        return False

def sincronizar_fichas_completas(filtro_cultivo: Optional[str] = None, limite: Optional[int] = None, db_path: Path = DB_DEFAULT):
    """
    Descarga los PDFs originales del MAPA, extrae el 100% de los datos y puebla las 8 tablas de la BD.
    """
    catalogo = obtener_catalogo_oficial_mapa()
    total_total = len(catalogo)

    # Filtrar por cultivo si se especifica (ej: hortícolas)
    if filtro_cultivo:
        filtro_lower = filtro_cultivo.lower()
        catalogo = [p for p in catalogo if any(filtro_lower in c.lower() for c in p.get("cultivos", []))]
        print(f"[*] Filtrado por cultivo '{filtro_cultivo}': {len(catalogo)} productos seleccionados de {total_total}.")
    else:
        print(f"[*] Modo Catálogo Completo: {len(catalogo)} productos seleccionados.")

    if limite:
        catalogo = catalogo[:limite]
        print(f"[*] Límite aplicado: procesando los primeros {limite} productos.")

    print("\n" + "=" * 75)
    print("🚀 INICIANDO DESCARGA Y PROCESAMIENTO CANÓNICO DE FICHAS OFICIALES EN PDF")
    print("=" * 75)

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TT-Editor/2.0 AgriTech-Sync"}
    client = httpx.Client(headers=headers, timeout=30.0, follow_redirects=True, verify=False)

    procesados = 0
    errores = 0
    t0 = time.perf_counter()

    for idx, prod in enumerate(catalogo, 1):
        num_reg = prod["num_registro"]
        nombre = prod["nombre_comercial"]
        
        print(f"[{idx}/{len(catalogo)}] Ficha {num_reg} ({nombre[:28]:<28})... ", end="", flush=True)
        
        ok = descargar_y_procesar_producto(prod, client, db_path=db_path)
        if ok:
            print("✅ OK (Datos extraídos y guardados)")
            procesados += 1
        else:
            print("⚠️  No disponible / Error")
            errores += 1

        # Pausa ética para respetar los servidores del MAPA
        time.sleep(0.3)

    t_total = time.perf_counter() - t0
    client.close()

    print("\n" + "=" * 75)
    print("🎉 DESCARGA Y EXTRACCIÓN DE FICHAS PDF COMPLETADA")
    print(f"  • Total Fichas Procesadas: {procesados}")
    print(f"  • Fichas con error / no disp: {errores}")
    print(f"  • Tiempo total: {t_total:.2f} s ({t_total/max(1, procesados):.2f} s por ficha)")
    print("=" * 75)

if __name__ == "__main__":
    # Prueba rápida con los primeros 3 productos
    sincronizar_fichas_completas(limite=3)
