"""
api_fitosanitarios.py - API REST de Alta Disponibilidad para TT EDITOR 2.0
Desarrollada con FastAPI y SQLite WAL. Permite consultas agronómicas en < 1 ms.
"""

import sqlite3
import time
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Query, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DB_FILE = Path(__file__).parent / "fitosanitarios_mapa.db"

app = FastAPI(
    title="API de Fitosanitarios MAPA (TT EDITOR 2.0)",
    description="Motor de prescripción agronómica y validación de recetas basado en la base de datos oficial 3FN.",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
    finally:
        conn.close()

# -----------------------------------------------------------------------------
# MODELOS PYDANTIC
# -----------------------------------------------------------------------------

class SolicitudValidacionReceta(BaseModel):
    num_registro: str = Field(..., description="Número de registro MAPA del producto")
    cultivo: str = Field(..., description="Nombre del cultivo (ej: 'Pimiento', 'Tomate')")
    dosis_prescrita: float = Field(..., description="Dosis prescrita por el técnico")
    unidad_prescrita: Optional[str] = Field(None, description="Unidad de la dosis (kg/ha, l/ha, %)")
    dias_para_cosecha: Optional[int] = Field(None, description="Días previstos hasta la recolección")

class RespuestaValidacionReceta(BaseModel):
    valido: bool
    bloqueante: bool
    mensajes: List[str]
    datos_oficiales: Optional[Dict[str, Any]] = None

# -----------------------------------------------------------------------------
# ENDPOINTS
# -----------------------------------------------------------------------------

@app.get("/api/v2/fitosanitarios/buscar", summary="Búsqueda instantánea de productos con autocompletado")
def buscar_productos(
    q: str = Query(..., min_length=2, description="Texto de búsqueda (nombre, registro o materia activa)"),
    db: sqlite3.Connection = Depends(get_db)
):
    t0 = time.perf_counter()
    cursor = db.cursor()
    patron = f"%{q.strip().upper()}%"
    
    cursor.execute("""
        SELECT DISTINCT
            p.id,
            p.num_registro,
            p.nombre_comercial,
            p.titular,
            p.estado,
            p.fecha_caducidad,
            COALESCE(GROUP_CONCAT(DISTINCT s.nombre), '') AS materias_activas
        FROM mapa_productos p
        LEFT JOIN mapa_producto_composicion c ON p.id = c.producto_id
        LEFT JOIN mapa_sustancias_activas s ON c.sustancia_id = s.id
        WHERE p.nombre_comercial LIKE ? 
           OR p.num_registro LIKE ?
           OR s.nombre LIKE ?
        GROUP BY p.id
        LIMIT 20;
    """, (patron, patron, patron))
    
    filas = [dict(row) for row in cursor.fetchall()]
    ms = (time.perf_counter() - t0) * 1000
    return {
        "tiempo_ms": round(ms, 3),
        "total_encontrados": len(filas),
        "resultados": filas
    }

@app.get("/api/v2/fitosanitarios/consultar-usos", summary="Motor de Prescripción Agronómica")
def consultar_usos_agronomicos(
    cultivo: str = Query(..., description="Cultivo diana (ej: 'Pimiento', 'Tomate')"),
    plaga: Optional[str] = Query(None, description="Plaga o agente diana (ej: 'Orugas', 'Trips')"),
    plazo_max: Optional[int] = Query(None, description="Plazo de seguridad máximo en días"),
    solo_vigentes: bool = Query(True, description="Filtrar únicamente productos vigentes"),
    db: sqlite3.Connection = Depends(get_db)
):
    t0 = time.perf_counter()
    cursor = db.cursor()
    
    sql = """
        SELECT 
            p.num_registro,
            p.nombre_comercial,
            p.titular,
            p.estado,
            u.cultivo_nombre,
            u.agente_nombre,
            u.dosis_original,
            u.dosis_min,
            u.dosis_max,
            u.dosis_unidad,
            u.num_aplicaciones_max,
            u.intervalo_min_dias,
            u.volumen_caldo,
            u.condiciones_especificas,
            u.plazo_seguridad_dias,
            u.plazo_seguridad_texto
        FROM mapa_usos u
        JOIN mapa_productos p ON u.producto_id = p.id
        WHERE u.cultivo_nombre LIKE ?
    """
    params = [f"%{cultivo.strip()}%"]
    
    if plaga:
        sql += " AND u.agente_nombre LIKE ?"
        params.append(f"%{plaga.strip()}%")
    if plazo_max is not None:
        sql += " AND u.plazo_seguridad_dias <= ?"
        params.append(plazo_max)
    if solo_vigentes:
        sql += " AND p.estado = 'Vigente'"
        
    sql += " ORDER BY p.nombre_comercial ASC LIMIT 50;"
    
    cursor.execute(sql, params)
    filas = [dict(row) for row in cursor.fetchall()]
    ms = (time.perf_counter() - t0) * 1000
    
    return {
        "tiempo_ms": round(ms, 3),
        "total_usos": len(filas),
        "usos_autorizados": filas
    }

@app.post("/api/v2/fitosanitarios/validar-receta", summary="Validación Automática de Seguridad y Legalidad de Prescripción", response_model=RespuestaValidacionReceta)
def validar_receta(
    datos: SolicitudValidacionReceta,
    db: sqlite3.Connection = Depends(get_db)
):
    cursor = db.cursor()
    
    # 1. Verificar si el producto existe
    cursor.execute("""
        SELECT id, num_registro, nombre_comercial, estado 
        FROM mapa_productos 
        WHERE num_registro = ?;
    """, (datos.num_registro.strip(),))
    prod = cursor.fetchone()
    if not prod:
        return RespuestaValidacionReceta(
            valido=False,
            bloqueante=True,
            mensajes=[f"El producto con número de registro {datos.num_registro} no existe en la base de datos oficial."]
        )
    
    prod_dict = dict(prod)
    mensajes = []
    bloqueante = False

    # 2. Verificar estado de vigencia
    if prod_dict["estado"].lower() != "vigente":
        mensajes.append(f"ADVERTENCIA: El producto {prod_dict['nombre_comercial']} está marcado como '{prod_dict['estado']}'. No se debe prescribir para nuevos tratamientos.")
        bloqueante = True

    # 3. Verificar si el cultivo está autorizado
    cursor.execute("""
        SELECT 
            dosis_min, dosis_max, dosis_unidad, dosis_original,
            plazo_seguridad_dias, plazo_seguridad_texto, condiciones_especificas
        FROM mapa_usos
        WHERE producto_id = ? AND cultivo_nombre LIKE ?
        LIMIT 1;
    """, (prod_dict["id"], f"%{datos.cultivo.strip()}%"))
    uso = cursor.fetchone()
    
    if not uso:
        mensajes.append(f"INFRACCIÓN LEGAL: El producto {prod_dict['nombre_comercial']} (Reg. {datos.num_registro}) NO está autorizado para el cultivo '{datos.cultivo}'.")
        return RespuestaValidacionReceta(
            valido=False,
            bloqueante=True,
            mensajes=mensajes,
            datos_oficiales={"producto": prod_dict}
        )

    uso_dict = dict(uso)

    # 4. Validar Dosis Máxima
    if uso_dict["dosis_max"] is not None and datos.dosis_prescrita > uso_dict["dosis_max"]:
        mensajes.append(
            f"DOSIS EXCESIVA: La dosis prescrita ({datos.dosis_prescrita} {datos.unidad_prescrita or ''}) supera el máximo legal autorizado ({uso_dict['dosis_max']} {uso_dict['dosis_unidad'] or ''})."
        )
        bloqueante = True
    elif uso_dict["dosis_min"] is not None and datos.dosis_prescrita < uso_dict["dosis_min"]:
        mensajes.append(
            f"DOSIS BAJA: La dosis prescrita ({datos.dosis_prescrita}) está por debajo del rango mínimo recomendado ({uso_dict['dosis_min']} {uso_dict['dosis_unidad'] or ''}). Riesgo de ineficacia o generación de resistencias."
        )

    # 5. Validar Plazo de Seguridad respecto a la cosecha prevista
    if datos.dias_para_cosecha is not None and uso_dict["plazo_seguridad_dias"] > 0:
        if datos.dias_para_cosecha < uso_dict["plazo_seguridad_dias"]:
            mensajes.append(
                f"BLOQUEO DE COSECHA: Quedan {datos.dias_para_cosecha} días para recolectar, pero el plazo de seguridad oficial es de {uso_dict['plazo_seguridad_dias']} días. Tratamiento bloqueado para evitar superación de LMRs."
            )
            bloqueante = True

    if not mensajes:
        mensajes.append("Prescripción conforme a la autorización oficial del MAPA.")

    return RespuestaValidacionReceta(
        valido=not bloqueante,
        bloqueante=bloqueante,
        mensajes=mensajes,
        datos_oficiales={
            "producto": prod_dict,
            "uso_autorizado": uso_dict
        }
    )

@app.get("/api/v2/fitosanitarios/producto/{num_registro}", summary="Ficha Técnica Canónica Completa")
def obtener_ficha_completa(num_registro: str, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM mapa_productos WHERE num_registro = ?;", (num_registro.strip(),))
    prod = cursor.fetchone()
    if not prod:
        raise HTTPException(status_code=404, detail="Producto fitosanitario no encontrado.")

    prod_id = prod["id"]
    
    # Composición
    cursor.execute("""
        SELECT s.nombre, s.numero_cas, c.concentracion, c.unidad
        FROM mapa_producto_composicion c
        JOIN mapa_sustancias_activas s ON c.sustancia_id = s.id
        WHERE c.producto_id = ?;
    """, (prod_id,))
    composicion = [dict(r) for r in cursor.fetchall()]

    # Usos
    cursor.execute("SELECT * FROM mapa_usos WHERE producto_id = ?;", (prod_id,))
    usos = [dict(r) for r in cursor.fetchall()]

    # Plazos
    cursor.execute("SELECT * FROM mapa_plazos_seguridad WHERE producto_id = ?;", (prod_id,))
    plazos = [dict(r) for r in cursor.fetchall()]

    # Seguridad y Toxicología
    cursor.execute("SELECT * FROM mapa_seguridad WHERE producto_id = ?;", (prod_id,))
    seguridad = cursor.fetchone()
    
    cursor.execute("SELECT * FROM mapa_toxicologia WHERE producto_id = ?;", (prod_id,))
    toxicologia = cursor.fetchone()

    return {
        "producto": dict(prod),
        "composicion": composicion,
        "usos_autorizados": usos,
        "plazos_seguridad": plazos,
        "seguridad": dict(seguridad) if seguridad else None,
        "toxicologia": dict(toxicologia) if toxicologia else None
    }
