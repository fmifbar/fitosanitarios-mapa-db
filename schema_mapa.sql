-- ============================================================================
-- ESQUEMA CANÓNICO FITOSANITARIOS MAPA (3ª FORMA NORMAL)
-- Proyecto: TT EDITOR 2.0 / Base de Datos Fitosanitarios
-- ============================================================================

PRAGMA foreign_keys = ON;

-- 1. Tabla Maestra de Productos Comerciales
CREATE TABLE IF NOT EXISTS mapa_productos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    num_registro TEXT NOT NULL UNIQUE,          -- Código numérico MAPA (ej: '19692')
    nombre_comercial TEXT NOT NULL,             -- Denominación comercial en mayúsculas
    titular TEXT NOT NULL,                      -- Empresa titular del registro
    fabricante TEXT,                            -- Entidad fabricante
    estado TEXT NOT NULL DEFAULT 'Vigente',     -- 'Vigente', 'Caducado', 'Cancelado'
    fecha_inscripcion DATE,
    fecha_renovacion DATE,                      -- Fecha de renovación administrativa del registro
    fecha_caducidad DATE,
    fecha_cancelacion DATE,                     -- Fecha oficial de cancelación del registro
    fecha_limite_venta DATE,                    -- Fecha límite de comercialización y venta
    titular_direccion TEXT,                     -- Dirección postal y sede del titular
    fabricante_direccion TEXT,                  -- Dirección postal y sede del fabricante
    fabrica TEXT,                               -- Fábrica / Instalación de producción química
    otras_denominaciones TEXT,                  -- Nombres comerciales secundarios / Marcas blancas
    envases_autorizados TEXT,                   -- Formatos y presentaciones comerciales autorizadas
    condiciones_generales_uso TEXT,             -- Directrices agronómicas, técnicas y restricciones generales
    observaciones_reglamentarias TEXT,          -- Normativa, orden toxicológica, SIGFITO y leyendas de etiqueta
    tipo_formulario TEXT,                       -- Polvo mojable (WP), Suspensión concentrada (SC), etc.
    clasificacion_peligrosidad TEXT,            -- Pictogramas CLP / Frases H
    pdf_url TEXT,                               -- URL de descarga en la web del ministerio
    pdf_sha256 TEXT,                            -- Hash para control de cambios sin re-parsear
    sincronizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Catálogo Normalizado de Sustancias Activas (Materias Activas)
CREATE TABLE IF NOT EXISTS mapa_sustancias_activas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,                -- Nombre normalizado (ej: 'AZADIRACTINA')
    nombre_ue TEXT,                             -- Denominación oficial en la UE / Inglés
    numero_cas TEXT,                            -- Registro químico CAS
    codigo_frac_irac TEXT                       -- Modo de acción (IRAC / FRAC / HRAC)
);

-- 3. Tabla Intermedia: Composición (Muchos a Muchos)
CREATE TABLE IF NOT EXISTS mapa_producto_composicion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES mapa_productos(id) ON DELETE CASCADE,
    sustancia_id INTEGER NOT NULL REFERENCES mapa_sustancias_activas(id) ON DELETE RESTRICT,
    concentracion REAL NOT NULL,                -- Valor cuantitativo
    unidad TEXT NOT NULL,                       -- '% (p/p)', 'g/l', etc.
    UNIQUE(producto_id, sustancia_id)
);

-- 4. Tabla de Autorizaciones de Usos (El núcleo agronómico SIEX/CUE)
CREATE TABLE IF NOT EXISTS mapa_usos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES mapa_productos(id) ON DELETE CASCADE,
    cultivo_nombre TEXT NOT NULL,               -- Nombre agronómico (ej: 'Tomate', 'Pimiento')
    codigo_cultivo TEXT,                        -- Código oficial MAPA/SIEX del cultivo
    agente_nombre TEXT NOT NULL,                -- Plaga o patógeno diana (ej: 'Orugas', 'Trips')
    codigo_agente TEXT,                         -- Código oficial MAPA/SIEX de la plaga
    dosis_min REAL,                             -- Cuantitativo mínimo para cálculo automático
    dosis_max REAL,                             -- Cuantitativo máximo para control de exceso
    dosis_unidad TEXT,                          -- 'kg/ha', 'l/ha', '%', 'ver condic.'
    dosis_original TEXT NOT NULL,               -- Texto íntegro extraído del PDF
    num_aplicaciones_max INTEGER,               -- Número máximo de aplicaciones por ciclo/año
    intervalo_min_dias INTEGER,                 -- Días mínimos entre pases
    volumen_caldo TEXT,                         -- Rango de caldo declarado (ej: '500-1000 l/ha')
    volumen_caldo_min REAL,                     -- Caldo numérico mínimo en l/ha para cálculos
    volumen_caldo_max REAL,                     -- Caldo numérico máximo en l/ha para cálculos
    ambito TEXT,                                -- Ámbito (ej: 'Aire libre', 'Invernadero', 'No Agrario')
    tipo_usuario TEXT,                          -- 'Profesional', 'No Profesional'
    metodo_aplicacion TEXT,                     -- Método (ej: 'Pulverización foliar', 'Goteo')
    bbch TEXT,                                  -- Estadio fenológico BBCH autorizado
    condiciones_especificas TEXT,               -- Observaciones legales de la fila
    plazo_seguridad_dias INTEGER DEFAULT 0,     -- Plazo de seguridad asignado (0 si es NP)
    plazo_seguridad_texto TEXT                  -- 'NO PROCEDE', '3', '7', etc.
);

-- 5. Plazos de Seguridad Declarados en Ficha
CREATE TABLE IF NOT EXISTS mapa_plazos_seguridad (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES mapa_productos(id) ON DELETE CASCADE,
    cultivo_o_grupo TEXT NOT NULL,              -- Ámbito (ej: 'Tomate', 'Cucurbitáceas')
    dias INTEGER DEFAULT 0,                     -- Número de días
    texto_declarado TEXT NOT NULL               -- '3', '14', 'NP', 'NO PROCEDE'
);

-- 6. Medidas de Mitigación de Riesgos Ecotoxicológicos
CREATE TABLE IF NOT EXISTS mapa_mitigaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES mapa_productos(id) ON DELETE CASCADE,
    tipo_organismo TEXT NOT NULL,               -- 'Acuático', 'Artrópodos no diana', 'Abejas'
    distancia_buffer_metros INTEGER DEFAULT 0,  -- Banda de seguridad en metros
    porcentaje_reduccion_deriva INTEGER,        -- % de reducción requerido (boquillas)
    texto_restriccion TEXT NOT NULL
);

-- 7. Seguridad Laboral y Prevención de Riesgos
CREATE TABLE IF NOT EXISTS mapa_seguridad (
    producto_id INTEGER PRIMARY KEY REFERENCES mapa_productos(id) ON DELETE CASCADE,
    seguridad_aplicador TEXT,                  -- Ropa 6-B, mascarilla FFP2, guantes...
    seguridad_trabajador TEXT,
    plazo_reentrada TEXT,                      -- 'No entrar hasta secado' o días específicos
    frases_reduccion_riesgo TEXT,              -- Ropa de trabajo, follaje húmedo, labores mecánicas...
    bandas_seguridad_spe3 TEXT,                -- 5m, 10m o 30m a masas de agua
    polinizadores_spe8 TEXT                    -- 'No aplicar en floración / 96 horas'
);

-- 8. Clasificación CLP, Toxicología y Mezclas
CREATE TABLE IF NOT EXISTS mapa_toxicologia (
    producto_id INTEGER PRIMARY KEY REFERENCES mapa_productos(id) ON DELETE CASCADE,
    palabra_advertencia TEXT,                  -- PELIGRO, ATENCIÓN, SIN ADVERTENCIA
    pictogramas_ghs TEXT,                      -- 'GHS07,GHS09'
    indicaciones_h TEXT,                       -- H319, H317, H410
    consejos_p TEXT,                           -- P280, P302+P352...
    incompatibilidades_mezclas TEXT,           -- 'No usar en combinación con...'
    gestion_envases TEXT                       -- Triple lavado y entrega a SIGFITO
);

-- ============================================================================
-- ÍNDICES DE ALTO RENDIMIENTO (Covering Indexes para latencia < 0.2 ms)
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_mapa_prod_registro ON mapa_productos(num_registro);
CREATE INDEX IF NOT EXISTS idx_mapa_prod_estado ON mapa_productos(estado);
CREATE INDEX IF NOT EXISTS idx_mapa_usos_busqueda ON mapa_usos(cultivo_nombre, agente_nombre);
CREATE INDEX IF NOT EXISTS idx_mapa_usos_prod_cultivo ON mapa_usos(producto_id, cultivo_nombre);
CREATE INDEX IF NOT EXISTS idx_mapa_plazos_prod ON mapa_plazos_seguridad(producto_id);
