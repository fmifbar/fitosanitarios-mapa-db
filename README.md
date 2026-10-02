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

## 📄 Fichas PDF: lo que el JSON del Ministerio no trae

El JSON nacional da el catálogo y los usos. **Lo demás solo está en el PDF de cada
ficha**: los EPIs del aplicador, el plazo de reentrada, las bandas de seguridad SPe3,
el aviso de abejas SPe8, los pictogramas y las frases H y P.

### Qué estaba pasando (corregido el 02/10/2026)

El paso de PDF estaba escrito (`descargador_fichas_mapa.py`, `enriquecer_desde_pdfs.py`)
pero **no corría nunca**, por dos motivos a la vez:

1. El workflow diario solo llamaba a `sincronizar_servidor.py`.
2. `cache_pdfs/` está en el `.gitignore` y el runner arranca limpio, así que aunque
   lo hubiera llamado habría encontrado cero PDF.

Con lo cual `mapa_seguridad`, `mapa_toxicologia` y `mapa_mitigaciones` llevaban
congeladas desde el principio. Y una tabla congelada es peor que una vacía: se
consulta igual y responde igual.

### La cadena nueva

```
catálogo oficial (JSON)
        ↓
enriquecer_fichas.py     incremental y con tope: solo las que faltan o han cambiado
        ↓
extractor_posicional.py  lee el PDF por POSICIÓN y COLOR, no como texto corrido
        ↓
adaptador_canonico.py    traduce al contrato de las 8 tablas
        ↓
etl_ingesta_mapa.py      carga en fitosanitarios_mapa.db
```

| Archivo | Qué hace |
|---|---|
| `extractor_posicional.py` | Lee la ficha por posición y color. **2.049 de 2.080 bien (98,5 %)** |
| `adaptador_canonico.py` | De la ficha a las ocho tablas |
| `enriquecer_fichas.py` | Orquesta: elige, descarga con pausa, extrae, carga |
| `test_adaptador_canonico.py` | 22 pruebas del contrato |
| `comprobar_cadena_completa.py` | Pasa un lote real por la cadena y cuenta qué ha entrado |

Medido sobre las 2.080 fichas: **0 excepciones**, 28.212 usos, 4.519 plazos, 6.214
mitigaciones, 2.075 filas de seguridad y 2.080 de toxicología.

### Por qué semanal, y por qué completo

**Semanal porque el Ministerio publica una vez por semana.** Lo dice su propia web:
*«esta base de datos se actualizará semanalmente»*, y la última actualización cuando
se escribió esto era del lunes 28/09/2026 a las 11:24. Pedirlas más a menudo es
bajarse lo mismo varias veces.

**Completo, y no por tandas, porque una ficha puede cambiar sin cambiar de estado.**
En la comparación del 02/10/2026 sobre 50 fichas, la única que había cambiado en dos
semanas (`ES-01265`) lo hizo en la fecha de caducidad, con el estado intacto. Un
criterio incremental la habría dejado esperando turno.

Lo que cuesta, medido contra el servidor del Ministerio:

| | |
|---|---|
| Por ficha | 0,1–0,2 s y 70–335 KB |
| Las 2.081 enteras | ~25–30 min y ~480 MB |
| Ritmo sostenido | ~0,6 peticiones/s, una vez por semana |

El PDF hay que bajarlo siempre: **el MAPA no admite peticiones condicionales**
(no devuelve `ETag` ni `Last-Modified`, comprobado el 02/10/2026). Lo que sí se evita
es el trabajo de después: si el SHA-256 coincide con el guardado, no se extrae ni se
escribe, así que la base apenas se mueve y el repositorio no engorda por esto.

```bash
python enriquecer_fichas.py              # todas
python enriquecer_fichas.py --tope 5     # para probar
```

El flujo corre **los domingos**, de modo que el lunes el técnico tenga la ficha de
cada producto. Nótese que el Ministerio publica **los lunes**, así que lo que se
recoge el domingo es la publicación del lunes anterior —que es la vigente hasta ese
momento—. Para recoger la del mismo lunes basta con mover el cron a `0 13 * * 1`.

### Dos cosas que conviene saber al leer estos datos

- **Lo que no se ha leído está en `NULL`, nunca en `0` ni en `""`.** Un plazo de
  reentrada vacío no significa que se pueda entrar ya.
- **Lo deducido va marcado como deducido.** En las fichas antiguas no existe el campo
  «Sistema de Cultivo»; lo que se saca del texto de condiciones es una interpretación,
  y así lo dice el propio campo.

---

## 🤖 Automatización en GitHub Actions

| Flujo | Cuándo | Qué hace |
|---|---|---|
| `actualizar_fitosanitarios.yml` | Diario, 04:00 UTC | Catálogo y usos desde el JSON del MAPA |
| `actualizar_fichas_pdf.yml` | Domingos, 05:00 UTC | Las 2.081 fichas PDF, barrido completo |

Los dos se pueden lanzar a mano desde **Actions** > el flujo > **Run workflow**.

---

## 📄 Licencia
Datos oficiales de carácter público procedentes del Ministerio de Agricultura, Pesca y Alimentación (MAPA) del Gobierno de España.
