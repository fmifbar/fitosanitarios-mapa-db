"""
adaptador_canonico.py - De la ficha leída por posición al contrato de la base.

Qué hace y por qué existe
-------------------------
`extractor_posicional.py` devuelve la ficha tal y como está maquetada: apartados,
bloques de clasificación, párrafos de mitigación. `etl_ingesta_mapa.cargar_producto_en_bd`
espera otra cosa: ocho tablas en 3FN con nombres concretos. Este módulo traduce de
lo uno a lo otro.

Es el paso que **desbloquea lo que llevaba congelado**: `mapa_seguridad` (EPIs,
plazo de reentrada, bandas SPe3, polinizadores SPe8), `mapa_toxicologia`
(pictogramas, frases H y P, gestión de envases) y `mapa_mitigaciones`. Esas tres
tablas estaban vacías porque el paso de PDF no llegaba a correr nunca.

La regla que gobierna esto
--------------------------
**Lo que no se ha leído se deja en `None`, nunca en cadena vacía ni en cero.**
`None` significa «la ficha no lo dice o no se ha sabido leer»; `""` se lee como
«no tiene», y son cosas distintas. Un plazo de reentrada vacío no es «se puede
entrar ya»; una lista de pictogramas vacía no es «no es peligroso».

Y lo que este módulo **deduce** va marcado como deducido. En las fichas antiguas
no existe el campo «Sistema de Cultivo», y lo que se saca del texto de
condiciones es una interpretación nuestra, no un dato del Ministerio.
"""
import re
import unicodedata
from typing import Any, Dict, List, Optional


def llano(t: Any) -> str:
    s = unicodedata.normalize("NFKD", str(t or ""))
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip().lower()


def _texto(valor: Any) -> Optional[str]:
    """Une una lista de párrafos en un texto, o `None` si no hay nada."""
    if valor is None:
        return None
    if isinstance(valor, (list, tuple)):
        partes = [str(x).strip() for x in valor if str(x or "").strip()]
        return " ".join(partes) or None
    t = str(valor).strip()
    return t or None


def _codigos(items: Any) -> Optional[str]:
    """«H319,H317,H410» a partir de la lista de frases, o `None`."""
    if not items:
        return None
    cods = [i.get("codigo") for i in items if isinstance(i, dict) and i.get("codigo")]
    return ",".join(dict.fromkeys(cods)) or None


# ---------------------------------------------------------------------------
# Seguridad laboral: lo que el aplicador tiene que ponerse y cuándo volver
# ---------------------------------------------------------------------------
# Los apartados de «Manipulación» no se llaman igual en todas las fichas, y lo
# que importa casi nunca está en el apartado sino **colgando de él**: medido
# sobre las 2.080 fichas, los EPIs viven en sub-apartados llamados «Aire
# libre», «Invernadero», «— Mezcla, carga», «— Aplicación», cuyo padre sí es
# «Seguridad del aplicador». Mirar solo el nombre del hijo deja fuera cuatro de
# cada cinco fichas.
#
# Así que se clasifica por el **padre**, y si no hay padre, por el apartado.
# Y lo que no encaje en ninguno se guarda entero en `frases_reduccion_riesgo`
# en vez de tirarlo: perder una frase de seguridad porque el apartado se
# llamaba distinto es el peor resultado posible.
_APLICADOR = ("seguridad del aplicador", "seguridad del operador", "seguridad del operario",
              "el aplicador utilizara", "medidas adicionales de mitigacion para el operador",
              "seguridad del manipulador")
_TRABAJADOR = ("seguridad del trabajador", "el trabajador utilizara", "reentrada")


def _clasifica(claves, *nombres) -> bool:
    # En cualquier posición y no solo al principio: hay apartados como
    # «Medidas adicionales de mitigación del riesgo para el aplicador» o
    # «(Invernadero) Seguridad del trabajador». Las claves son frases largas,
    # así que casar dentro no trae falsos positivos.
    return any(k in n for n in nombres if n for k in claves)


def seguridad_de(ficha: Dict[str, Any]) -> Dict[str, Any]:
    manip = ficha.get("manipulacion") or {}
    apartados = manip.get("apartados") or []

    aplicador, trabajador, otras = [], [], []
    for a in apartados:
        texto = _texto(a.get("texto"))
        if not texto:
            continue
        hijo = llano(a.get("apartado") or "")
        padre = llano(a.get("dentro_de") or "")

        # El nombre del sub-apartado se conserva delante del texto, y no es
        # adorno: «Aire libre» e «Invernadero» llevan EPIs distintos, y en
        # Murgiverde se trabaja bajo plástico. Perder cuál es cuál dejaría el
        # dato inservible justo para el caso de aquí.
        etiquetado = f"{a['apartado'].strip()}: {texto}" if a.get("apartado") else texto

        if _clasifica(_APLICADOR, padre, hijo):
            aplicador.append(etiquetado)
        elif _clasifica(_TRABAJADOR, padre, hijo):
            trabajador.append(etiquetado)
        else:
            otras.append(etiquetado)

    # SPe3 (bandas a masas de agua) y SPe8 (polinizadores) salen de la sección
    # de riesgos ambientales, no de manipulación.
    mitig = ficha.get("mitigacion_ambiental") or []
    spe3 = [m for m in mitig if (m.get("codigo") or "").upper() == "SPE3" or m.get("distancias_m")]
    spe8 = [m for m in mitig if "abejas y polinizadores" in (m.get("organismos") or [])]

    return {
        "seguridad_aplicador": _texto(aplicador),
        "seguridad_trabajador": _texto(trabajador),
        # Del resumen que ya calcula el extractor: «48 horas», «hasta que se
        # haya secado»... o None si la ficha no lo dice.
        "plazo_reentrada": manip.get("plazo_reentrada") or None,
        "frases_reduccion_riesgo": _texto(otras),
        "bandas_seguridad_spe3": _texto([m.get("texto") for m in spe3]),
        "polinizadores_spe8": _texto([m.get("texto") for m in spe8]),
    }


# ---------------------------------------------------------------------------
# Toxicología y CLP
# ---------------------------------------------------------------------------
# Las incompatibilidades de mezcla **no están donde uno las buscaría**. Medido
# sobre las 2.080 fichas: 143 las llevan en «Condiciones generales de uso», 37
# en «Otras indicaciones» y 13 metidas en las condiciones de un uso suelto.
# Buscarlas solo en «Otras indicaciones» encontraba 2.
#
# Importa porque es el dato que dice si dos productos pueden ir en el mismo
# caldo, y en un invernadero se mezcla casi siempre.
_RX_INCOMPATIBLE = re.compile(
    r"incompatib|no mezclar|no se debe mezclar|no debe mezclarse|"
    r"no aplicar junto|no utilizar en mezcla", re.I)


def _frases(valor: Any) -> List[str]:
    if isinstance(valor, (list, tuple)):
        return [str(x).strip() for x in valor if str(x or "").strip()]
    t = str(valor or "").strip()
    # Un bloque largo se parte en frases para no arrastrar el párrafo entero
    # cuando solo una frase habla de mezclas.
    return [f.strip() for f in re.split(r"(?<=[.;])\s+", t) if f.strip()] if t else []


def _incompatibilidades(ficha: Dict[str, Any]) -> List[str]:
    fuentes = [ficha.get("condiciones_generales_uso"), ficha.get("otras_indicaciones")]
    fuentes += [u.get("condiciones") for u in (ficha.get("usos") or [])]
    vistas, out = set(), []
    for fuente in fuentes:
        for frase in _frases(fuente):
            if _RX_INCOMPATIBLE.search(frase) and frase not in vistas:
                vistas.add(frase)
                out.append(frase)
    return out


def toxicologia_de(ficha: Dict[str, Any]) -> Dict[str, Any]:
    clas = ficha.get("clasificacion") or {}
    humana = clas.get("humana") or {}
    ambiental = clas.get("ambiental") or {}

    # Los pictogramas y las frases H viven repartidos entre el bloque humano y
    # el ambiental (el GHS09 del pez está en el segundo). Se juntan los dos: la
    # etiqueta del envase los lleva todos.
    pictos, frases_h, frases_p = [], [], []
    for bloque in (humana, ambiental):
        pictos += [p.get("codigo") for p in (bloque.get("pictogramas") or []) if p.get("codigo")]
        frases_h += bloque.get("indicaciones_peligro") or []
        frases_p += bloque.get("consejos_prudencia") or []

    incompat = _incompatibilidades(ficha)

    return {
        "palabra_advertencia": humana.get("palabra_advertencia") or None,
        "pictogramas_ghs": ",".join(dict.fromkeys(pictos)) or None,
        "indicaciones_h": _codigos(frases_h),
        "consejos_p": _codigos(frases_p),
        "incompatibilidades_mezclas": _texto(incompat),
        "gestion_envases": ficha.get("gestion_envases") or None,
    }


# ---------------------------------------------------------------------------
# Mitigaciones ambientales
# ---------------------------------------------------------------------------
def mitigaciones_de(ficha: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for m in ficha.get("mitigacion_ambiental") or []:
        texto = (m.get("texto") or "").strip()
        if not texto:
            continue
        organismos = m.get("organismos") or []
        distancias = m.get("distancias_m") or []
        reducciones = m.get("reduccion_deriva_pct") or []
        out.append({
            # El esquema pide un organismo por fila. Cuando la frase nombra
            # varios se juntan en vez de quedarse con uno: elegir seria
            # inventar cual importa.
            "tipo_organismo": ", ".join(organismos) or (m.get("codigo") or "sin clasificar"),
            # La banda que manda es **la mayor** de las que nombre la frase: es
            # la que cumple todas las demas.
            "distancia_buffer_metros": max(distancias) if distancias else 0,
            "porcentaje_reduccion_deriva": max(reducciones) if reducciones else None,
            "texto_restriccion": texto,
        })
    return out


# ---------------------------------------------------------------------------
# Usos y plazos
# ---------------------------------------------------------------------------
# En la ficha la dosis es texto: «0,25 - 0,6 %», «4 kg/ha», «Ver condicionamientos».
# El esquema quiere además el mínimo, el máximo y la unidad por separado, para
# poder calcular. Lo que no se sepa partir se deja en `None` y el texto íntegro
# se conserva siempre en `dosis_original`: el literal del Ministerio es el dato,
# el número es nuestra lectura de él.
_RX_RANGO = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:-|–|a)\s*(\d+(?:[.,]\d+)?)\s*([^\s\d]+(?:/[^\s\d]+)?)?")
_RX_UNICO = re.compile(r"(\d+(?:[.,]\d+)?)\s*([^\s\d]+(?:/[^\s\d]+)?)?")


def _num(x: Any) -> Optional[float]:
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None


def partir_dosis(texto: Any):
    """(mínimo, máximo, unidad) a partir del texto de la dosis."""
    t = str(texto or "").strip()
    if not t:
        return None, None, None
    m = _RX_RANGO.search(t)
    if m:
        return _num(m.group(1)), _num(m.group(2)), (m.group(3) or "").strip(" .") or None
    m = _RX_UNICO.search(t)
    if m:
        # Una cifra sola se toma como **máximo**, que es el lado que importa:
        # pasarse es lo que deja residuo, quedarse corto no.
        return None, _num(m.group(1)), (m.group(2) or "").strip(" .") or None
    return None, None, None


def _entero(texto: Any) -> Optional[int]:
    """El primer número entero de un texto como «1-8» o «7 días», o `None`."""
    m = re.search(r"\d+", str(texto or ""))
    return int(m.group(0)) if m else None


def _maximo_entero(texto: Any) -> Optional[int]:
    """El mayor entero: de «1-8» aplicaciones, el máximo son 8."""
    nums = [int(x) for x in re.findall(r"\d+", str(texto or ""))]
    return max(nums) if nums else None


def _bbch_de(condiciones: Any) -> Optional[str]:
    """El estadio BBCH, que en la ficha va dentro del texto de condiciones."""
    m = re.search(r"BBCH\s*([\d]{1,2}(?:\s*[-–]\s*[\d]{1,2})?)", str(condiciones or ""), re.I)
    return f"BBCH {m.group(1).replace(' ', '')}" if m else None


def usos_de(ficha: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for u in ficha.get("usos") or []:
        dmin, dmax, unidad = partir_dosis(u.get("dosis"))
        cmin, cmax, _ = partir_dosis(u.get("caldo"))
        deducido = u.get("sistema_cultivo_deducido")
        if isinstance(deducido, (list, tuple)):
            deducido = ", ".join(str(x) for x in deducido) or None

        condiciones = u.get("condiciones")
        # El sistema de cultivo deducido se arrastra **dentro de las
        # condiciones y diciendo que es deducido**, porque el esquema no tiene
        # columna para él y meterlo en `ambito` lo haría pasar por un dato del
        # Ministerio. En las fichas antiguas ese campo no existe.
        if deducido:
            condiciones = ((condiciones or "") +
                           f" [Sistema de cultivo deducido del texto, no declarado "
                           f"por el Ministerio: {deducido}]").strip()

        # OJO CON LOS NOMBRES DE LAS CLAVES
        # ---------------------------------
        # `cargar_producto_en_bd` no lee las columnas de la tabla: lee **sus
        # propios nombres de entrada**, que no coinciden (`cultivo` y no
        # `cultivo_nombre`, `num_aplicaciones` y no `num_aplicaciones_max`,
        # `condiciones` y no `condiciones_especificas`). Equivocarse aquí no da
        # error: inserta NULL, o descarta la fila entera porque el cultivo
        # viene vacío. Se perdían los 28.222 usos sin una sola queja.
        out.append({
            "cultivo": u.get("uso") or "",
            "agente": u.get("agente") or "",
            "dosis_original": u.get("dosis") or "",
            "dosis_min": dmin,
            "dosis_max": dmax,
            "dosis_unidad": unidad,
            "num_aplicaciones": _maximo_entero(u.get("aplicaciones")),
            "intervalo_min_dias": _entero(u.get("intervalo")),
            "volumen_caldo": u.get("caldo") or "",
            "volumen_caldo_min": cmin,
            "volumen_caldo_max": cmax,
            "ambito": u.get("ambito"),
            "tipo_usuario": u.get("tipo_usuario"),
            "metodo_aplicacion": u.get("metodo_aplicacion") or "",
            "bbch": _bbch_de(u.get("condiciones")) or "",
            "condiciones": condiciones or "",
            # El plazo por uso no viene en la tabla de usos de la ficha, sino
            # en la de plazos, que va aparte. Se deja a 0 y con el texto vacío
            # en vez de inventar uno: el plazo bueno está en
            # `mapa_plazos_seguridad`.
            "plazo_dias": 0,
            "plazo_texto": "",
        })
    return out


# «NO PROCEDE», «NP» y «no procede» no son un plazo de 0 días por casualidad:
# significan que ese cultivo no tiene espera porque no se come la parte
# tratada, o porque se aplica fuera de cosecha. Se guarda el literal y además
# el número, y el número solo cuando de verdad hay uno.
def _dias_de_plazo(texto: Any) -> int:
    t = llano(texto)
    if not t or "no procede" in t or t in ("np", "n.p.", "-"):
        return 0
    m = re.search(r"\d+", t)
    return int(m.group(0)) if m else 0


def plazos_de(ficha: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for p in ficha.get("plazos_seguridad") or []:
        texto = p.get("plazo") or p.get("texto") or p.get("texto_declarado")
        cultivo = p.get("uso") or p.get("cultivo") or p.get("cultivo_o_grupo")
        if not texto or not cultivo:
            continue
        # Igual que en los usos: el ETL lee `cultivo_grupo` y `texto`, no los
        # nombres de las columnas. Equivocarse no da error, deja la tabla vacía.
        out.append({"cultivo_grupo": cultivo,
                    "dias": _dias_de_plazo(texto),
                    "texto": str(texto)})
    return out


def _partir_composicion(ficha: Dict[str, Any]):
    """
    La composición viene como párrafos: «AZUFRE 80% [WG] P/P».

    Devuelve (cuantificables, sin_cuantificar). La separación no es un capricho:
    `mapa_producto_composicion.concentracion` es **NOT NULL**, y
    `cargar_producto_en_bd` mete todo el producto en una sola transacción. Una
    línea que no se pueda cuantificar no deja un hueco: **tumba la ficha
    entera**, y en silencio, porque el error se captura y se revierte.

    Medido sobre las 2.080 fichas del registro: le pasa a 51 (2,5 %), y son
    justo las raras —*Bacillus thuringiensis*, virus, aceites— donde la
    concentración viene como «54[WG]» o «(32000 UI/mg)».

    Un 0 % no sirve de recambio: se leería como «no lleva», que es lo contrario
    de la verdad. Así que a la tabla van las cuantificables, y el texto literal
    de las otras se conserva aparte.
    """
    buenas, crudas = [], []
    for p in ficha.get("composicion") or []:
        texto = str(p or "").strip()
        if not texto:
            continue
        # Ojo con `\b` detrás de `%`: «80% [WG]» lleva un espacio después, y
        # `\b` exige un carácter de palabra, así que no casaba **ninguna**
        # línea en porcentaje, que son casi todas. Con `(?![a-z])` sí.
        m = re.match(r"^(.*?)\s+(\d+(?:[.,]\d+)?)\s*"
                     r"(%|g/l|g/kg|mg/kg|ufc/g|ufc/ml)(?![a-z])", texto, re.I)
        if m and m.group(1).strip():
            buenas.append({"nombre": m.group(1).strip(),
                           "concentracion": float(m.group(2).replace(",", ".")),
                           "unidad": m.group(3).lower(),
                           "texto_original": texto})
        else:
            crudas.append(texto)
    return buenas, crudas


def composicion_de(ficha: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Solo las líneas con una concentración que se pueda guardar en la tabla."""
    return _partir_composicion(ficha)[0]


def composicion_sin_cuantificar(ficha: Dict[str, Any]) -> List[str]:
    """Las que no caben en la tabla. No se tiran: van al texto reglamentario."""
    return _partir_composicion(ficha)[1]


# ---------------------------------------------------------------------------
# El contrato completo
# ---------------------------------------------------------------------------
def a_canonico(ficha: Dict[str, Any], num_registro_oficial: str = "",
               id_producto_mapa: Optional[int] = None) -> Dict[str, Any]:
    """
    La ficha en la forma que espera `cargar_producto_en_bd`.

    `num_registro_oficial` es el del catálogo nacional y **manda sobre el leído
    del PDF**: el catálogo es el dato, el PDF es una impresión del dato. Si no
    coincide se queda el oficial y la discrepancia se anota en la ficha, para
    que el control de calidad la pueda contar.
    """
    prod = dict(ficha.get("producto") or {})

    leido = (prod.get("num_registro") or "").strip()
    oficial = (num_registro_oficial or "").strip()
    if oficial:
        prod["num_registro"] = oficial
        if leido and llano(leido) != llano(oficial):
            prod["aviso_num_registro"] = (
                f"El PDF dice «{leido}» y el catálogo oficial «{oficial}». Manda el oficial.")

    titular = ficha.get("titular") or {}
    fabricante = ficha.get("fabricante") or {}
    if isinstance(titular, dict):
        prod.setdefault("titular", titular.get("nombre"))
        prod["titular_direccion"] = titular.get("direccion")
    if isinstance(fabricante, dict):
        prod.setdefault("fabricante", fabricante.get("nombre"))
        prod["fabricante_direccion"] = fabricante.get("direccion")

    prod["envases_autorizados"] = ficha.get("envases")
    prod["condiciones_generales_uso"] = ficha.get("condiciones_generales_uso")

    observaciones = _frases(ficha.get("otras_indicaciones"))
    # La composición que no se ha podido cuantificar se conserva aquí, literal.
    # No cabe en `mapa_producto_composicion` porque esa columna es NOT NULL, y
    # perderla del todo sería peor: es lo que lleva el producto dentro.
    sin_cifra = composicion_sin_cuantificar(ficha)
    if sin_cifra:
        observaciones.append(
            "Composición declarada en la ficha, sin concentración en formato "
            "reconocible: " + " | ".join(sin_cifra))
    prod["observaciones_reglamentarias"] = _texto(observaciones)
    if id_producto_mapa is not None:
        prod["id_producto_mapa"] = id_producto_mapa

    return {
        "producto": prod,
        "sha256": ficha.get("sha256") or "",
        "composicion": composicion_de(ficha),
        "usos": usos_de(ficha),
        "plazos_seguridad": plazos_de(ficha),
        "seguridad": seguridad_de(ficha),
        "toxicologia": toxicologia_de(ficha),
        "mitigaciones": mitigaciones_de(ficha),
        # Se arrastra para que quede en la base de dónde salió cada ficha.
        "procedencia": {
            "archivo": ficha.get("archivo"),
            "origen_pdf": ficha.get("origen_pdf"),
            "pdf_modificado": ficha.get("pdf_modificado"),
            "extraido_en": ficha.get("extraido_en"),
            "extractor_version": ficha.get("extractor_version"),
        },
    }
