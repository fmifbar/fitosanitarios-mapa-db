# 🌾 Base de Datos Relacional de Fitosanitarios MAPA (3FN) y JSON Canónico

[![Actualizar Fitosanitarios MAPA](https://github.com/fmifbar/fitosanitarios-mapa-db/actions/workflows/actualizar_fitosanitarios.yml/badge.svg)](https://github.com/fmifbar/fitosanitarios-mapa-db/actions/workflows/actualizar_fitosanitarios.yml)
[![Database](https://img.shields.io/badge/SQLite-3FN%20WAL-blue.svg)](fitosanitarios_mapa.db)
[![JSON](https://img.shields.io/badge/JSON-Unified%20Catalog-green.svg)](fitosanitarios_mapa_completo.json)
[![FastAPI](https://img.shields.io/badge/API-FastAPI%20%7C%20Swagger-009688.svg)](http://localhost:8000/docs)

**Proyecto:** TT EDITOR 2.0  
**Ámbito:** Soberanía del Dato Agronómico, Extracción Canónica y Consultas de Alta Disponibilidad  
**Fuente Oficial:** Ministerio de Agricultura, Pesca y Alimentación (MAPA) de España  

---

## 🏗️ Arquitectura del Sistema

Este repositorio implementa la extracción canónica, almacenamiento relacional en **Tercera Forma Normal (3FN)**, exportación a **JSON jerárquico unificado** y automatización en la nube con **GitHub Actions** para el catálogo oficial de fitosanitarios del MAPA.

### Diagrama de Flujo

```
┌─────────────────────────────────────────────────────────────┐
│  Ministerio de Agricultura, Pesca y Alimentación (MAPA)     │
│  - Exportación JSON Nacional (Productos + Usos Oficiales)   │
│  - Fichas Técnicas Oficiales en PDF (A3 Landscape)          │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│  GitHub Actions (Robot Autónomo Semanal)                   │
│  - Se ejecuta cada lunes a las 04:00 AM UTC                 │
│  - Ejecuta sincronizar_servidor.py                          │
└──────────────────────────────┬──────────────────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
┌──────────────────────────────┐    ┌──────────────────────────────┐
│ fitosanitarios_mapa.db       │    │ fitosanitarios_mapa_         │
│ - SQLite 3FN con WAL         │    │ completo.json                │
│ - 8 tablas relacionales      │    │ - Catálogo unificado         │
│ - Latencia de consulta < 1ms │    │ - 100% de datos en un JSON   │
└──────────────┬───────────────┘    └──────────────────────────────┘
               │
               ▼
┌──────────────────────────────┐
│ api_fitosanitarios.py        │
│ - Servidor FastAPI local     │
│ - Swagger UI en /docs        │
└──────────────────────────────┘
```

---

## 📊 Métricas de la Base de Datos

| Tabla Relacional | Contenido | Registros Actuales |
| :--- | :--- | :---: |
| `mapa_productos` | Identificación comercial, titular, fabricante y vigencia | **2.080** |
| `mapa_sustancias_activas` | Materias activas normalizadas y códigos CAS / IRAC | **377** |
| `mapa_producto_composicion` | Formulación cuantitativa y unidades (%) | **2.544** |
| `mapa_usos` | Usos agronómicos, dosis mín/máx, intervalos y volumen | **62.616** |
| `mapa_plazos_seguridad` | Días de espera antes de recolección por cultivo | **431** |
| `mapa_seguridad` | EPIs de aplicador (UNE-EN), operario y plazo de reentrada | **417** |
| `mapa_toxicologia` | Clasificación CLP, frases H, consejos P y pictogramas GHS | **557** |
| `mapa_mitigaciones` | Bandas de seguridad ambiental SPe3 y protección fauna | **662** |

---

## 🚀 Opciones de Uso

### 1. Ejecutable Interactivo de Escritorio (.exe)
Haz doble clic en `DescargadorFitosanitariosMAPA.exe` para abrir la consola de gestión:
- `[1]` Descargar FICHAS PDF Originales y extraer seguridad, toxicología y mitigaciones.
- `[2]` Sincronización Rápida Nacional (actualización en 5 segundos).
- `[3]` Buscador interactivo por cultivo, plaga, producto o materia activa.
- `[4]` Estadísticas en tiempo real de las 8 tablas.
- `[5]` Iniciar Servidor API REST (FastAPI).
- `[6]` Procesar carpeta de PDFs locales.
- `[7]` Exportar base de datos a `fitosanitarios_mapa_completo.json`.

### 2. Sincronización Automática en Servidor o Local
```powershell
# Instalar dependencias
pip install -r requirements.txt

# Sincronizar catálogo y regenerar JSON en un solo comando
python sincronizar_servidor.py
```

### 3. Levantar la API FastAPI
```powershell
uvicorn api_fitosanitarios:app --reload --port 8000
```
Documentación Swagger interactiva: `http://localhost:8000/docs`.

---

## 🤖 Automatización en GitHub Actions

El flujo `.github/workflows/actualizar_fitosanitarios.yml` se ejecuta:
- **Programado:** Cada lunes a las 04:00 AM UTC.
- **Manual:** Desde la pestaña **Actions** > **Sincronizar Fitosanitarios MAPA** > **Run workflow**.

---

## 📄 Licencia
Datos oficiales de carácter público procedentes del Ministerio de Agricultura, Pesca y Alimentación (MAPA) del Gobierno de España.
