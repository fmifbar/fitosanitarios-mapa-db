"""
init_db.py - Inicializador de la Base de Datos Relacional de Fitosanitarios (MAPA)
Configura SQLite con modo WAL (Write-Ahead Logging) y claves foráneas activas.
"""

import sqlite3
import os
from pathlib import Path

DB_FILE = Path(__file__).parent / "fitosanitarios_mapa.db"
SCHEMA_FILE = Path(__file__).parent / "schema_mapa.sql"

def inicializar_base_datos(db_path: Path = DB_FILE, schema_path: Path = SCHEMA_FILE):
    print(f"[*] Conectando a la base de datos: {db_path.name}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Optimizaciones clave para alto rendimiento y fiabilidad:
    # 1. Modo WAL: permite lecturas y escrituras simultáneas sin bloqueos.
    # 2. Claves foráneas: garantiza la integridad referencial (3FN).
    # 3. Synchronous NORMAL: máxima velocidad manteniendo durabilidad adecuada.
    cursor.execute("PRAGMA journal_mode = WAL;")
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("PRAGMA synchronous = NORMAL;")
    cursor.execute("PRAGMA cache_size = -64000;")  # ~64 MB de caché en RAM

    print(f"[*] Leyendo esquema SQL desde: {schema_path.name}")
    with open(schema_path, "r", encoding="utf-8") as f:
        script_sql = f.read()

    print("[*] Creando tablas e índices canónicos...")
    cursor.executescript(script_sql)
    conn.commit()

    # Verificación de tablas creadas
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tablas = [row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")]

    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' ORDER BY name;")
    indices = [row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")]

    print(f"\n[+] Base de datos inicializada con éxito:")
    print(f"    - Tablas ({len(tablas)}): {', '.join(tablas)}")
    print(f"    - Índices ({len(indices)}): {', '.join(indices)}")

    conn.close()

if __name__ == "__main__":
    inicializar_base_datos()
