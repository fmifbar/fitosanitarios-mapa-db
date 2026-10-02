"""
test_adaptador_canonico.py - Que lo extraído del PDF entre de verdad en la base.

Qué vigila
----------
El adaptador traduce de la ficha leída por posición al contrato de ocho tablas
que espera `cargar_producto_en_bd`. Son dos formas distintas de nombrar lo
mismo, y basta con que una clave no se llame igual para que un campo se pierda
**en silencio**: la carga no falla, simplemente guarda `NULL`.

Por eso aquí no se comprueba que «no casca», sino que **los datos llegan**: se
monta una base limpia desde `schema_mapa.sql`, se mete una ficha por la cadena
entera y se leen las ocho tablas a ver qué hay dentro.

La regla de fondo
-----------------
Lo que no se ha leído se queda en `None`, nunca en `""` ni en `0`. `None` es
«la ficha no lo dice»; `0` se lee como «no hay espera» y `""` como «no tiene».
Un plazo de reentrada vacío no significa que se pueda entrar ya.

Uso:
    python -m pytest test_adaptador_canonico.py -v
"""
import sqlite3
import tempfile
from pathlib import Path

import pytest

from adaptador_canonico import (a_canonico, composicion_de, mitigaciones_de, partir_dosis,
                                plazos_de, seguridad_de, toxicologia_de, usos_de)
from etl_ingesta_mapa import cargar_producto_en_bd

BASE = Path(__file__).parent


# Una ficha con la forma exacta que devuelve `extractor_posicional.extraer`,
# recortada a lo que importa aquí. Los textos son del estilo de los reales.
FICHA = {
    "archivo": "Ficha_ES-00001.pdf",
    "origen_pdf": "/tmp/cache_pdfs",
    "pdf_modificado": "2026-09-18T10:00:00",
    "sha256": "a" * 64,
    "extraido_en": "2026-10-02T08:00:00",
    "extractor_version": "1.1 (02/10/2026)",
    "producto": {
        "num_registro": "ES-00001",
        "nombre_comercial": "PRODUCTO DE PRUEBA",
        "estado": "Vigente",
        "fecha_inscripcion": "2020-01-01",
        "fecha_caducidad": "2030-01-01",
    },
    "titular": {"nombre": "EMPRESA S.A.", "direccion": "Calle Falsa 1, Almería"},
    "fabricante": {"nombre": "FABRICA S.L.", "direccion": "Polígono 2, Murcia"},
    "composicion": ["AZUFRE 80% [WG] P/P", "SUSTANCIA SIN CIFRA"],
    "envases": "Bolsa de 5 kg",
    "condiciones_generales_uso": "Aplicar con pulverizador. No mezclar con productos alcalinos.",
    "usos": [
        {"uso": "Tomate", "agente": "Oídio", "dosis": "0,25 - 0,6 %",
         "aplicaciones": "1-8", "intervalo": "7 días", "caldo": "500-666 l/ha",
         "ambito": "Aire libre", "tipo_usuario": "Profesional",
         "metodo_aplicacion": "Pulverización foliar", "sistema_cultivo": None,
         "condiciones": "Aplicar desde BBCH 13-85.", "sistema_cultivo_deducido": ["invernadero"]},
        {"uso": "Pepino", "agente": "Araña roja", "dosis": "4 kg/ha",
         "aplicaciones": "2", "intervalo": None, "caldo": None,
         "ambito": "Invernadero", "condiciones": None, "sistema_cultivo_deducido": None},
    ],
    "plazos_seguridad": [
        {"uso": "Tomate", "plazo": "3"},
        {"uso": "Pepino", "plazo": "NO PROCEDE"},
    ],
    "manipulacion": {
        "apartados": [
            {"apartado": "Seguridad del aplicador", "dentro_de": None, "texto": []},
            {"apartado": "Invernadero", "dentro_de": "Seguridad del aplicador",
             "texto": ["Guantes de protección química y mascarilla FFP2."]},
            {"apartado": "Seguridad del trabajador", "dentro_de": None,
             "texto": ["No entrar hasta que el producto se haya secado."]},
            {"apartado": "Normativa aplicable a los EPIs", "dentro_de": None,
             "texto": ["Los EPI cumplirán el RD 1407/1992."]},
        ],
        "plazo_reentrada": "hasta que se haya secado",
    },
    "clasificacion": {
        "humana": {"palabra_advertencia": "ATENCIÓN",
                   "pictogramas": [{"codigo": "GHS07", "texto": "GHS07"}],
                   "indicaciones_peligro": [{"codigo": "H319", "texto": "Irritación ocular grave"}],
                   "consejos_prudencia": [{"codigo": "P280", "texto": "Llevar guantes"}]},
        "ambiental": {"pictogramas": [{"codigo": "GHS09", "texto": "GHS09"}],
                      "indicaciones_peligro": [{"codigo": "H410", "texto": "Muy tóxico para los peces"}]},
    },
    "mitigacion_ambiental": [
        {"codigo": "SPe3", "organismos": ["organismos acuáticos"], "distancias_m": [5, 10],
         "reduccion_deriva_pct": [50], "horas": [], "no_aplicar_en_floracion": False,
         "texto": "SPe3: Para proteger los organismos acuáticos, respétese una banda de 10 m."},
        {"codigo": "SPe8", "organismos": ["abejas y polinizadores"], "distancias_m": [],
         "reduccion_deriva_pct": [], "horas": [96], "no_aplicar_en_floracion": True,
         "texto": "SPe8: Peligroso para las abejas. No aplicar en floración."},
    ],
    "gestion_envases": "Triple lavado y entrega a SIGFITO.",
    "otras_indicaciones": ["Producto incompatible con azufre micronizado."],
}


@pytest.fixture
def db():
    """Una base limpia montada desde el esquema del repositorio."""
    ruta = Path(tempfile.mkdtemp()) / "prueba.db"
    con = sqlite3.connect(ruta)
    try:
        con.executescript((BASE / "schema_mapa.sql").read_text(encoding="utf-8"))
        con.commit()
    finally:
        con.close()
    return ruta


def _filas(ruta, tabla, donde=""):
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(f"SELECT * FROM {tabla} {donde}")]
    finally:
        con.close()


# --------------------------------------------------------------------------
# La cadena entera
# --------------------------------------------------------------------------

def test_la_ficha_entra_en_las_ocho_tablas(db):
    cargar_producto_en_bd(a_canonico(FICHA, "ES-00001"), "Ficha_ES-00001.pdf",
                          db_path=db, forzar=True)

    assert len(_filas(db, "mapa_productos")) == 1
    assert len(_filas(db, "mapa_usos")) == 2
    assert len(_filas(db, "mapa_plazos_seguridad")) == 2
    assert len(_filas(db, "mapa_seguridad")) == 1
    assert len(_filas(db, "mapa_toxicologia")) == 1
    assert len(_filas(db, "mapa_mitigaciones")) == 2


def test_las_tres_tablas_que_estaban_congeladas_se_rellenan(db):
    """
    `mapa_seguridad`, `mapa_toxicologia` y `mapa_mitigaciones` llevaban vacías
    desde siempre porque el paso de PDF no corría. Esto es lo que lo arregla,
    así que es lo que hay que vigilar.
    """
    cargar_producto_en_bd(a_canonico(FICHA, "ES-00001"), "f.pdf", db_path=db, forzar=True)

    seg = _filas(db, "mapa_seguridad")[0]
    assert "FFP2" in (seg["seguridad_aplicador"] or "")
    assert "secado" in (seg["seguridad_trabajador"] or "")
    assert seg["plazo_reentrada"] == "hasta que se haya secado"
    assert "10 m" in (seg["bandas_seguridad_spe3"] or "")
    assert "abejas" in (seg["polinizadores_spe8"] or "").lower()

    tox = _filas(db, "mapa_toxicologia")[0]
    assert tox["palabra_advertencia"] == "ATENCIÓN"
    assert tox["pictogramas_ghs"] == "GHS07,GHS09"
    assert tox["indicaciones_h"] == "H319,H410"
    assert tox["consejos_p"] == "P280"
    assert "SIGFITO" in (tox["gestion_envases"] or "")


def test_el_epi_de_invernadero_no_pierde_su_etiqueta(db):
    """
    «Aire libre» e «Invernadero» llevan EPIs distintos, y en Murgiverde se
    trabaja bajo plástico. Si se juntan sin decir cuál es cuál, el dato deja de
    servir justo para el caso de aquí.
    """
    seg = seguridad_de(FICHA)
    assert seg["seguridad_aplicador"].startswith("Invernadero:")


# --------------------------------------------------------------------------
# Lo que no se sabe se queda en None
# --------------------------------------------------------------------------

def test_lo_que_la_ficha_no_dice_queda_en_none():
    vacia = {"producto": {"num_registro": "ES-9"}, "usos": [], "manipulacion": {},
             "clasificacion": None, "mitigacion_ambiental": []}
    seg, tox = seguridad_de(vacia), toxicologia_de(vacia)

    assert seg["plazo_reentrada"] is None
    assert seg["seguridad_aplicador"] is None
    assert tox["pictogramas_ghs"] is None
    assert tox["palabra_advertencia"] is None
    # Ni cadenas vacías ni ceros: se leerían como «no tiene», que es otra cosa.
    assert "" not in seg.values()
    assert 0 not in tox.values()


def test_una_sustancia_sin_cifra_no_tumba_la_ficha_entera(db):
    """
    El fallo que esto cierra. `concentracion` es NOT NULL y la carga va en una
    sola transacción, así que una línea sin cifra reconocible no dejaba un
    hueco: **revertía el producto completo**, y en silencio. Le pasa a 51 de
    las 2.080 fichas (2,5 %): *Bacillus thuringiensis*, virus, aceites.
    """
    cargar_producto_en_bd(a_canonico(FICHA, "ES-00001"), "f.pdf", db_path=db, forzar=True)

    assert len(_filas(db, "mapa_productos")) == 1, "la ficha entera se ha perdido"
    comp = {c["nombre"]: c for c in composicion_de(FICHA)}
    assert comp["AZUFRE"]["concentracion"] == 80.0
    assert "SUSTANCIA SIN CIFRA" not in comp


def test_la_composicion_sin_cifra_no_se_tira(db):
    """Es lo que lleva el producto dentro: se conserva literal, aparte."""
    cargar_producto_en_bd(a_canonico(FICHA, "ES-00001"), "f.pdf", db_path=db, forzar=True)

    obs = _filas(db, "mapa_productos")[0]["observaciones_reglamentarias"] or ""
    assert "SUSTANCIA SIN CIFRA" in obs
    assert "sin concentración en formato reconocible" in obs


def test_nunca_se_inventa_un_cero_por_ciento():
    """Un 0 % se leería como «no lleva», que es lo contrario de la verdad."""
    assert all(c["concentracion"] for c in composicion_de(FICHA))


# --------------------------------------------------------------------------
# Dosis, plazos y mitigaciones
# --------------------------------------------------------------------------

@pytest.mark.parametrize("texto,esperado", [
    ("0,25 - 0,6 %", (0.25, 0.6, "%")),
    ("4 kg/ha", (None, 4.0, "kg/ha")),
    ("500-666 l/ha", (500.0, 666.0, "l/ha")),
    ("Ver condicionamientos", (None, None, None)),
    ("", (None, None, None)),
])
def test_la_dosis_se_parte_bien(texto, esperado):
    assert partir_dosis(texto) == esperado


def test_una_cifra_sola_es_el_maximo():
    """Pasarse de dosis es lo que deja residuo; quedarse corto, no."""
    minimo, maximo, _ = partir_dosis("4 kg/ha")
    assert minimo is None and maximo == 4.0


def test_el_texto_integro_de_la_dosis_se_conserva_siempre():
    """El literal del Ministerio es el dato; el número es nuestra lectura."""
    assert usos_de(FICHA)[0]["dosis_original"] == "0,25 - 0,6 %"


def test_no_procede_se_guarda_como_tal_y_no_solo_como_cero():
    por_cultivo = {p["cultivo_grupo"]: p for p in plazos_de(FICHA)}
    assert por_cultivo["Pepino"]["texto"] == "NO PROCEDE"
    assert por_cultivo["Tomate"]["dias"] == 3


def test_el_numero_maximo_de_aplicaciones_es_el_mayor():
    """De «1-8», el máximo son 8, que es el límite que hay que respetar."""
    assert usos_de(FICHA)[0]["num_aplicaciones"] == 8


def test_la_banda_de_seguridad_que_manda_es_la_mayor():
    """De «5 m o 10 m», la que cumple las dos es 10."""
    acuaticos = [m for m in mitigaciones_de(FICHA) if "acuáticos" in m["tipo_organismo"]][0]
    assert acuaticos["distancia_buffer_metros"] == 10


def test_el_bbch_sale_de_las_condiciones():
    assert usos_de(FICHA)[0]["bbch"] == "BBCH 13-85"


# --------------------------------------------------------------------------
# Procedencia y deducciones
# --------------------------------------------------------------------------

def test_el_sistema_de_cultivo_deducido_va_marcado_como_deducido():
    """
    En las fichas antiguas ese campo no existe. Lo que sacamos del texto es una
    interpretación nuestra y no puede pasar por un dato del Ministerio.
    """
    cond = usos_de(FICHA)[0]["condiciones"]
    assert "deducido" in cond.lower()
    assert "no declarado por el Ministerio" in cond


def test_manda_el_registro_del_catalogo_y_la_discrepancia_se_anota():
    """El catálogo es el dato; el PDF es una impresión del dato."""
    d = a_canonico(FICHA, "ES-99999")
    assert d["producto"]["num_registro"] == "ES-99999"
    assert "ES-00001" in d["producto"]["aviso_num_registro"]


def test_se_arrastra_de_donde_salio_la_ficha():
    p = a_canonico(FICHA, "ES-00001")["procedencia"]
    assert p["origen_pdf"] == "/tmp/cache_pdfs"
    assert p["pdf_modificado"] == "2026-09-18T10:00:00"
    assert p["extractor_version"]


def test_las_incompatibilidades_se_buscan_donde_estan_de_verdad():
    """
    Medido sobre las 2.080 fichas: 143 las llevan en «Condiciones generales de
    uso» y solo 37 en «Otras indicaciones». Buscarlas solo en la segunda
    encontraba 2.
    """
    texto = toxicologia_de(FICHA)["incompatibilidades_mezclas"] or ""
    assert "alcalinos" in texto          # de condiciones_generales_uso
    assert "azufre micronizado" in texto  # de otras_indicaciones


# --------------------------------------------------------------------------
# Qué fichas entran en cada pasada
# --------------------------------------------------------------------------

def _catalogo(n):
    return [{"num_registro": f"ES-{i:05d}", "id_producto": i, "estado": "Vigente"}
            for i in range(n)]


def test_el_barrido_completo_no_se_deja_ninguna():
    """
    `tope = 0` significa todas, y es lo normal: el Ministerio publica una vez
    por semana y se recoge entera. El motivo de no ir por tandas es que **una
    ficha puede cambiar sin cambiar de estado** —como ES-01265, que cambió la
    caducidad— y por tandas se quedaría esperando turno.
    """
    from enriquecer_fichas import elegir
    assert len(elegir(_catalogo(2081), {}, tope=0)) == 2081


def test_con_tope_se_recorta_pero_por_prioridad():
    """
    Si la pasada se corta —se agota el runner, se cae la red— lo que haya
    entrado tiene que ser lo que más falta hacía, no lo primero por orden
    alfabético.
    """
    from enriquecer_fichas import elegir
    cat = _catalogo(10)
    guardado = {p["num_registro"]: {"estado": "Vigente", "sha": "x", "cuando": "2026-01-01"}
                for p in cat}
    guardado["ES-00007"]["sha"] = None      # a esta no se le ha sacado nunca la ficha

    elegidas = elegir(cat, guardado, tope=3)

    assert elegidas[0]["num_registro"] == "ES-00007"
    assert len(elegidas) == 3


def test_un_cambio_de_estado_adelanta_la_ficha():
    from enriquecer_fichas import elegir
    cat = _catalogo(5)
    cat[3]["estado"] = "Cancelado"
    guardado = {p["num_registro"]: {"estado": "Vigente", "sha": "x", "cuando": "2026-01-01"}
                for p in cat}

    assert elegir(cat, guardado, tope=1)[0]["num_registro"] == "ES-00003"
